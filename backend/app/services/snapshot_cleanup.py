"""表快照清理：读取快照记录、计算可恢复快照集合、生成数据表快照清理结果。

保留策略版本与快照创建方式共同决定候选；恢复链（回滚记录）与分支引用
（分支记录）也参与判断，遗漏任一来源都会误删仍可恢复的版本。清理结果
持久化在内存仓库里：快照页的清理结果与回滚工作台待办共用同一份数据，
核对结论写回同一条记录，保证两侧一致。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

SNAPSHOT_MODULE = "snapshot"
ROLLBACK_MODULE = "rollback"
BRANCH_MODULE = "branch"
POLICY_MODULE = "snapshot_policy"
RESULT_MODULE = "snapshot_cleanup_result"

RETENTION_TIERS = {"7天": 7, "14天": 14, "30天": 30}
BOUNDARIES = ["按创建时间", "按最近访问时间"]
COVERED_METHODS = ["定时调度", "触发式"]
VERIFY_CONCLUSIONS = ["核对一致", "核对不一致"]
VERIFY_PENDING = "待核对"


def _today() -> date:
    return date.today()


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


class SnapshotCleanupService:
    """读取表快照记录并计算可恢复快照集合，再生成数据表快照清理结果。"""

    # ---------- 保留策略 ----------
    def get_policy(self) -> dict[str, Any]:
        """返回当前已确认的保留策略；没有时登记默认版本，不重新计算。"""
        rows = store.rows(POLICY_MODULE)
        if not rows:
            rows.append({
                "策略版本": "RET-0001",
                "保留档位": "7天",
                "保留天数": RETENTION_TIERS["7天"],
                "保留边界": "按创建时间",
                "适用创建方式": list(COVERED_METHODS),
                "确认时间": "2026-11-10 09:00:00",
            })
        return dict(rows[-1])

    def confirm_policy(self, tier: str, boundary: str) -> tuple[dict[str, Any] | None, str]:
        """确认保留档位与保留边界：生成新策略版本，并按新边界重新生成清理结果。"""
        if tier not in RETENTION_TIERS:
            return None, f"保留档位「{tier}」不在可选范围（{'、'.join(RETENTION_TIERS)}）"
        if boundary not in BOUNDARIES:
            return None, f"保留边界「{boundary}」不在可选范围（{'、'.join(BOUNDARIES)}）"
        current = self.get_policy()
        if current["保留档位"] == tier and current["保留边界"] == boundary:
            return current, "保留策略与上次确认版本一致，清理依据保持不变"
        version_no = int(str(current["策略版本"]).split("-")[-1]) + 1
        policy = {
            "策略版本": f"RET-{version_no:04d}",
            "保留档位": tier,
            "保留天数": RETENTION_TIERS[tier],
            "保留边界": boundary,
            "适用创建方式": list(COVERED_METHODS),
            "确认时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        store.rows(POLICY_MODULE).append(policy)
        self.refresh_cleanup_result()
        return policy, f"保留策略已确认为 {policy['策略版本']}，清理结果已按新边界重新生成"

    # ---------- 可恢复快照集合 ----------
    def read_snapshot_records(self) -> list[dict[str, Any]]:
        """读取表快照记录。"""
        return [row for row in store.rows(SNAPSHOT_MODULE) if str(row.get("快照编号", "")).strip()]

    def compute_recoverable_set(self) -> dict[str, list[str]]:
        """恢复链（回滚记录）与分支引用（分支记录）共同构成可恢复快照集合。"""
        refs: dict[str, list[str]] = {}
        for row in store.rows(ROLLBACK_MODULE):
            snap = str(row.get("回滚版本", "")).strip()
            if snap:
                refs.setdefault(snap, []).append(f"被恢复链引用：{row.get('记录编号', '')}")
        for row in store.rows(BRANCH_MODULE):
            if row.get("status") == "已删除":
                continue
            snap = str(row.get("引用快照", "")).strip()
            if snap:
                refs.setdefault(snap, []).append(f"被分支引用：{row.get('分支编号', '')}")
        return refs

    # ---------- 数据表快照清理结果 ----------
    def generate_cleanup_result(self) -> dict[str, Any]:
        """按当前保留策略生成清理结果：每条候选都带保留或删除依据。"""
        policy = self.get_policy()
        refs = self.compute_recoverable_set()
        retention_days = int(policy["保留天数"])
        boundary = str(policy["保留边界"])
        today = _today()
        candidates: list[dict[str, Any]] = []
        keep = delete = 0
        for row in self.read_snapshot_records():
            snap_id = str(row.get("快照编号", "")).strip()
            method = str(row.get("创建方式", "")).strip()
            created = _parse_date(row.get("快照时间"))
            accessed = _parse_date(row.get("最近访问时间")) or created
            if snap_id in refs:
                decision = "保留"
                basis = "；".join(refs[snap_id]) + "，仍可恢复，禁止清理"
            elif method not in policy["适用创建方式"]:
                decision = "保留"
                basis = f"创建方式「{method}」不在策略覆盖范围"
            else:
                anchor = created if boundary == "按创建时间" else accessed
                age = (today - anchor).days if anchor else 0
                if age <= retention_days:
                    decision = "保留"
                    basis = f"在保留期内（{boundary}，{age} 天 ≤ {retention_days} 天）"
                    if boundary == "按最近访问时间" and accessed and created and accessed > created:
                        basis += "，保留较新的访问快照"
                else:
                    decision = "删除"
                    basis = f"超过保留期（{boundary}，{age} 天 > {retention_days} 天）"
                    if boundary == "按创建时间":
                        basis += "，按创建批次淘汰"
            if decision == "保留":
                keep += 1
            else:
                delete += 1
            candidates.append({
                "快照编号": snap_id,
                "表名称": row.get("表名称", ""),
                "创建方式": method,
                "快照时间": row.get("快照时间", ""),
                "最近访问时间": row.get("最近访问时间", ""),
                "决策": decision,
                "依据": basis,
                "核对结论": VERIFY_PENDING,
            })
        return {
            "策略版本": policy["策略版本"],
            "保留档位": policy["保留档位"],
            "保留边界": boundary,
            "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "候选总数": len(candidates),
            "保留数": keep,
            "删除数": delete,
            "候选明细": candidates,
        }

    def refresh_cleanup_result(self) -> dict[str, Any]:
        """重新生成清理结果并持久化；回滚工作台待办随之更新。"""
        result = self.generate_cleanup_result()
        rows = store.rows(RESULT_MODULE)
        rows.clear()
        for idx, item in enumerate(result["候选明细"], start=1):
            rows.append({
                "id": idx,
                "策略版本": result["策略版本"],
                "生成时间": result["生成时间"],
                **item,
            })
        return result

    def get_cleanup_result(self) -> dict[str, Any]:
        """读取已生成的清理结果；页面刷新只读持久化数据，不覆盖清理依据。"""
        rows = store.rows(RESULT_MODULE)
        if not rows:
            return self.refresh_cleanup_result()
        policy = self.get_policy()
        keep = sum(1 for row in rows if row.get("决策") == "保留")
        return {
            "策略版本": rows[0].get("策略版本", policy["策略版本"]),
            "保留档位": policy["保留档位"],
            "保留边界": policy["保留边界"],
            "生成时间": rows[0].get("生成时间", ""),
            "候选总数": len(rows),
            "保留数": keep,
            "删除数": len(rows) - keep,
            "候选明细": [dict(row) for row in rows],
        }

    # ---------- 回滚工作台待办 ----------
    def list_workbench_todos(self) -> list[dict[str, Any]]:
        """回滚清单：基于同一份数据表快照清理结果生成待办。"""
        rows = store.rows(RESULT_MODULE)
        if not rows:
            self.refresh_cleanup_result()
            rows = store.rows(RESULT_MODULE)
        return [{
            "id": int(row["id"]),
            "待办编号": f"TODO-{int(row['id']):04d}",
            "快照编号": row["快照编号"],
            "表名称": row.get("表名称", ""),
            "决策": row["决策"],
            "依据": row["依据"],
            "核对结论": row.get("核对结论", VERIFY_PENDING),
            "来源": "数据表快照清理结果",
        } for row in rows]

    def verify_todo(self, todo_id: int, conclusion: str) -> tuple[dict[str, Any] | None, str]:
        """核对单条待办：核对结论写回清理结果，快照页与回滚工作台保持一致。"""
        if conclusion not in VERIFY_CONCLUSIONS:
            return None, f"核对结论「{conclusion}」不在可选范围（{'、'.join(VERIFY_CONCLUSIONS)}）"
        row = store.find(RESULT_MODULE, todo_id)
        if row is None:
            return None, f"回滚工作台待办 {todo_id} 不存在或已归档"
        row["核对结论"] = conclusion
        return row, f"待办 TODO-{todo_id:04d} 已核对为「{conclusion}」"
