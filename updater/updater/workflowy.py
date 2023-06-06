from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

import lxml.html
import regex
import sqlalchemy as sa
from pydantic import BaseModel

from updater.database import create_engine
from updater.settings import settings
from updater.utils import requests_get

# Getting and parsing the workflowy tree
#
WF_CLIENT_VERSION = 23
AUTH_URL = "https://workflowy.com/api/auth"
DATA_URL = f"https://workflowy.com/get_initialization_data?client_version={WF_CLIENT_VERSION}"


class WorkflowyData(BaseModel):
    projectTreeData: ProjectTreeData


class ProjectTreeData(BaseModel):
    mainProjectTreeInfo: MainProjectTreeInfo


class MainProjectTreeInfo(BaseModel):
    # root node when viewing a shared project, otherwise null
    rootProject: Optional[Node]
    rootProjectChildren: List[Node]
    # all "lm" attributes in rootProjectChildren are relative to this timestamp
    dateJoinedTimestampInSeconds: int
    auxiliaryProjectTreeInfos: Optional[List[MainProjectTreeInfo]]


class Node(BaseModel):
    id: UUID
    # name
    nm: str
    # notes
    no: Optional[str]
    # created
    ct: int
    # last modified
    lm: int
    # completed at
    cp: Optional[int]
    # children
    ch: Optional[List[Node]]
    metadata: NodeMetadata


class NodeMetadata(BaseModel):
    mirror: Optional[Dict]
    originalId: Optional[UUID]
    isVirtualRoot: Optional[bool]
    virtualRootIds: Optional[Dict[UUID, bool]]


WorkflowyData.update_forward_refs()
MainProjectTreeInfo.update_forward_refs()
ProjectTreeData.update_forward_refs()
Node.update_forward_refs()


@dataclass
class WorkflowyItem:
    ref_id: UUID
    text: str
    notes: str
    tags: Set[str]
    parents: List[WorkflowyItem] = field(repr=False)
    children: List[WorkflowyItem]
    created_at: datetime
    modified_at: datetime
    completed_at: Optional[datetime]


def get_worklfowy_items() -> Dict[UUID, WorkflowyItem]:
    request = requests_get(DATA_URL, headers={"cookie": f"sessionid={settings.WORKFLOWY_SESSION_ID}"})
    request.raise_for_status()
    data = WorkflowyData.parse_raw(request.text)
    return flatten_tree(data)


def flatten_tree(data: WorkflowyData) -> Dict[UUID, WorkflowyItem]:
    time_joined_s = data.projectTreeData.mainProjectTreeInfo.dateJoinedTimestampInSeconds
    nodes = data.projectTreeData.mainProjectTreeInfo.rootProjectChildren

    items: Dict[UUID, WorkflowyItem] = {}
    add_children(nodes, items, parent=None, time_joined_s=time_joined_s)

    return items


def add_children(
    nodes: List[Node], items: Dict[UUID, WorkflowyItem], parent: Optional[WorkflowyItem], time_joined_s: int
) -> List[WorkflowyItem]:
    """Recursively convert and add child nodes to items"""
    converted_nodes = []
    for node in nodes:
        item = convert_node(node, parent, time_joined_s)
        converted_nodes.append(item)

        assert item.ref_id not in items
        items[item.ref_id] = item

        if node.ch:
            item.children = add_children(node.ch, items, parent=item, time_joined_s=time_joined_s)
    return converted_nodes


def convert_node(node: Node, parent: Optional[WorkflowyItem], time_joined_s: int) -> WorkflowyItem:
    text = node.nm
    notes = node.no or ""
    tags = find_tags(text)

    created_at = datetime.fromtimestamp(time_joined_s + node.ct, timezone.utc)
    modfied_at = datetime.fromtimestamp(time_joined_s + node.lm, timezone.utc)

    if parent:
        parent_completed_at = parent.completed_at
        parents = parent.parents + [parent]
    else:
        parent_completed_at = None
        parents = []

    completed_at = parent_completed_at
    if node.cp is not None:
        completed_at = datetime.fromtimestamp(time_joined_s + node.cp, timezone.utc)

    return WorkflowyItem(
        ref_id=node.id,
        text=text,
        notes=notes,
        tags=tags,
        parents=parents,
        children=[],  # Will be set by the caller
        created_at=created_at,
        modified_at=modfied_at,
        completed_at=completed_at,
    )


# Using regex package instead of re for better unicode class support (\p{L} and \p{Nd}).
# Also interesting: http://unicode.org/reports/tr18/
# The source of this regex is workflowy itself.
WORKFLOWY_TAG_REGEX = regex.compile(
    r"(^|\s|[(),.!?;:\/\[\]])([#@]([\p{L}\p{Nd}][\p{L}\p{Nd}\-_']*(:([\p{L}\p{Nd}][\p{L}\p{Nd}\-_']*))*))(?=$|\s|[(),.!?;:\/\[\]])"
)
WORKFLOWY_NOT_TAG_REGEX = regex.compile(r"^[0-9]{1,3}$")


def find_tags(text: str) -> Set[str]:
    """Find all tags in text that workflowy considers a tag"""
    matches = WORKFLOWY_TAG_REGEX.findall(text)
    tags = {m[2] for m in matches if not WORKFLOWY_NOT_TAG_REGEX.match(m[2])}
    tags = {tag.lower() for tag in tags}
    return tags


# Extracting microstuff
#
MICROSTUFF_TAG_NAME = "microstuff"


@dataclass
class Microstuff:
    time: datetime
    value: float
    comment: Optional[str]


def find_microstuff_roots(items: Dict[UUID, WorkflowyItem]) -> List[WorkflowyItem]:
    """Find all items that have a #microstuff tag"""
    return [item for item in items.values() if MICROSTUFF_TAG_NAME in item.tags]


def extract_microstuff(root_item: WorkflowyItem) -> List[Microstuff]:
    # Find all descendants of root that contain a date, then find all descendants of these date-items that contain a
    # number
    microstuffs = []
    root_descendants = root_item.children.copy()
    while len(root_descendants):
        item = root_descendants.pop()
        date_ = parse_datetime(item.text)

        # Go deeper if that item does not contain a date
        if not date_:
            root_descendants.extend(item.children)
            continue

        date_descendants = item.children.copy()
        while len(date_descendants):
            descendant = date_descendants.pop()
            date_descendants.extend(descendant.children)

            result = parse_value_and_comment(descendant.text)
            if not result:
                continue
            microstuffs.append(Microstuff(date_, result[0], result[1]))

    return microstuffs


def parse_datetime(item_text: str) -> Optional[datetime]:
    if not item_text:
        return

    # We only consider the first workflowy <time></time> tag to be a valid date here.
    # Example: <time startYear="2023" startMonth="1" startDay="28">Sat, Jan 28, 2023</time>
    parsed = lxml.html.fromstring(item_text)
    time_elem = None
    if parsed.tag == "time":
        time_elem = parsed
    else:
        time_elem = parsed.find("time")

    if time_elem is None:
        return

    return datetime(
        year=int(time_elem.get("startyear")),
        month=int(time_elem.get("startmonth")),
        day=int(time_elem.get("startday")),
        # Represent pure dates as midnight
        hour=maybe_int(time_elem.get("starthour")) or 0,
        minute=maybe_int(time_elem.get("startminute")) or 0,
        second=maybe_int(time_elem.get("startsecond")) or 0,
        # The <time/> tag does not have any timezone information
        tzinfo=ZoneInfo("Europe/Berlin"),
    )


def maybe_int(string: Optional[str]) -> Optional[int]:
    if string:
        return int(string)
    return None


def parse_value_and_comment(item_text: str) -> Optional[Tuple[float, Optional[str]]]:
    numbers = re.findall(r"\b\d+\b", item_text)
    if not len(numbers):
        return
    value = sum(float(n) for n in numbers)

    # Everything after the last number is the comment
    comment_match = re.search(r"[^\d]+$", item_text)
    comment = comment_match.group(0).strip(" ()") if comment_match else None
    comment = comment if comment else None  # Convert empty string to None

    return value, comment


# Storage
#
db_engine = create_engine()
metadata_obj = sa.MetaData()

table_name = "microstuff"
table = sa.Table(
    table_name,
    metadata_obj,
    sa.Column("time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("value", sa.Float, nullable=False),
    sa.Column("comment", sa.Text, nullable=True),
)


def init():
    # Create the table if it does not exist
    if not sa.inspect(db_engine).has_table(table_name):
        with db_engine.begin() as conn:
            table.create(conn, checkfirst=True)
            stmt = sa.text(
                "SELECT create_hypertable(:table, :time_column, migrate_data => true, if_not_exists => true)"
            )
            conn.execute(stmt, {"table": table_name, "time_column": "time"})


def update():
    items = get_worklfowy_items()

    for root_item in find_microstuff_roots(items):
        microstuff = extract_microstuff(root_item)
        metric_name = root_item.text.lower().replace(f"#{MICROSTUFF_TAG_NAME}", "").strip()

        rows = [{"time": ms.time, "name": metric_name, "value": ms.value, "comment": ms.comment} for ms in microstuff]
        with db_engine.begin() as conn:
            conn.execute(sa.delete(table).where(table.c.name == metric_name))
            conn.execute(sa.insert(table), rows)


if __name__ == "__main__":
    init()
    update()
