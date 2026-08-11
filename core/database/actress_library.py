"""core.database.actress_library — 庫內女優聚合（spec-117 子模組，TASK-117-T1）。

【Opus 裁決 ①】分組／聚合的單一所有者。這是**第三個**模組同時 import `.actress`
與 `.alias`——先例：`core.database.migrate` 同形狀 import `.video`（見該檔）。
`actress.py` 與 `alias.py` 之間仍然零依賴，這個模組才是組合點。分組是領域邏輯
（「誰跟誰是同一人、算幾片」），不是 HTTP 關注點，所以不放 router 層。
"""
from typing import List

from .actress import ActressRepository
from .alias import AliasRepository


def get_library_actresses() -> List[dict]:
    """依 alias group 聚合庫內全部女優，回傳每筆 { primary_name, names[], video_count,
    is_favorite }。

    規則（§1.1 定死 + Opus 裁決 ②）：
      - pairs = ActressRepository().get_video_actress_pairs()——一次查詢拿到全部
        (rowid, actress_name) 配對。
      - name → (primary_name, names[]) 由 AliasRepository().get_all() 建一次 lookup dict
        （primary_name 與每個 alias 都指向同一組 (primary_name, [primary_name]+aliases)）；
        lookup miss 時 group_key = name 本身，names = [name]。
      - video_count = 該 group 的 set(rowid) 長度（Python 側 DISTINCT，CD-117-2）。
      - is_favorite：`favorite_names = {a.name for a in ActressRepository().get_all()}`
        建一次集合，判定 `primary_name in favorite_names`——讀 `actresses` 表同一欄，
        不查 alias 表是否存在該 group（迴圈內不得逐一呼叫 exists()，Opus 裁決 ②）。
      - 排序 = video_count desc, primary_name asc（AC-2.2 穩定次序）。

    排除 0 片（AC-2.7）天然成立：group 只可能由 pairs（有片子的名字）建立，不
    outer join 收藏表。

    整支函式全程只開 3 次連線（pairs 一次、alias get_all() 一次、favorites get_all()
    一次），與 group 數無關——迴圈內是純 Python 記憶體分組，不開任何 DB 連線。
    """
    pairs = ActressRepository().get_video_actress_pairs()

    # name -> (primary_name, names_list)；names_list 對同一 group 內每個名字共用同一物件
    lookup: dict = {}
    for record in AliasRepository().get_all():
        names_list = [record.primary_name] + list(record.aliases)
        for n in names_list:
            lookup[n] = (record.primary_name, names_list)

    favorite_names = {a.name for a in ActressRepository().get_all()}

    groups: dict = {}  # primary_name -> {"names": list, "rowids": set}
    for rowid, name in pairs:
        primary_name, names_list = lookup.get(name, (name, [name]))
        group = groups.get(primary_name)
        if group is None:
            group = {"names": names_list, "rowids": set()}
            groups[primary_name] = group
        group["rowids"].add(rowid)

    result = [
        {
            "primary_name": primary_name,
            "names": group["names"],
            "video_count": len(group["rowids"]),
            "is_favorite": primary_name in favorite_names,
        }
        for primary_name, group in groups.items()
    ]
    result.sort(key=lambda g: (-g["video_count"], g["primary_name"]))
    return result
