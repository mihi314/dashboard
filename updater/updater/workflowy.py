from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

import lxml.html
import requests
import sqlalchemy as sa
from pydantic import BaseModel

from updater.database import create_engine
from updater.settings import settings

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
    request = requests.get(DATA_URL, headers={"cookie": f"sessionid={settings.WORKFLOWY_SESSION_ID}"})
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
    tags = set({})  # Not used/parsed currently

    created_at = datetime.fromtimestamp(time_joined_s + node.ct, timezone.utc)
    modfied_at = datetime.fromtimestamp(time_joined_s + node.lm, timezone.utc)

    if parent:
        parent_completed_at = parent.completed_at
        parents = parent.parents + [parent]
        tags |= parent.tags
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


# Extracting microstuff
#
@dataclass
class Microstuff:
    time: date
    value: float
    comment: Optional[str]


def extract_microstuff(items: Dict[UUID, WorkflowyItem], root_uuid: UUID) -> List[Microstuff]:
    if root_uuid not in items:
        print(f"Warning: {root_uuid} not found in workflowy tree")
        return []

    # Find all descendants of root data contain a date,
    # then find all descendants of these date-items that contain a number
    root = items[root_uuid]
    microstuffs = []

    root_descendants = root.children.copy()
    while len(root_descendants):
        item = root_descendants.pop()
        date_ = parse_date(item.text)

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


def parse_date(item_text: str) -> Optional[date]:
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

    return date(
        year=int(time_elem.get("startyear")),
        month=int(time_elem.get("startmonth")),
        day=int(time_elem.get("startday")),
    )


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
    sa.Column("time", sa.Date, nullable=False),
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

    micromarriages = extract_microstuff(items, UUID("bcea1f2a-11e0-5a2d-99a2-569985d46b24"))
    metric_name = "micromarriages"

    rows = [{"time": mm.time, "name": metric_name, "value": mm.value, "comment": mm.comment} for mm in micromarriages]
    with db_engine.begin() as conn:
        conn.execute(sa.delete(table).where(table.c.name == metric_name))
        conn.execute(sa.insert(table), rows)


if __name__ == "__main__":
    init()
    update()
