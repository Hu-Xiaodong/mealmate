"""后台权限点目录。

权限点是后端鉴权的最小单位，接口通过 require_permission("post.review")
声明自己需要哪一个。这里集中维护“系统支持哪些权限点”和中文名称，
后台角色编辑页直接读取这份目录，避免前端写死、后端新增权限后漏配。
"""

PERMISSION_LABELS: dict[str, str] = {
    "post.review": "审核饭帖",
    "post.unpublish": "下架饭帖",
    "post.delete": "删除饭帖",
    "user.read": "查看用户",
    "user.ban": "封禁与解封用户",
    "recipe.manage": "菜谱管理",
    "taste_tag.manage": "口味标签维护",
    "dashboard.read": "查看数据看板",
    "ai.log.read": "查看 AI 日志",
    "ai.config.write": "修改 AI 配置",
    # 评测写入单独一个权限点：能给回答打分的人不一定能改模型配置，
    # 这样运营可以参与质量评估，但碰不到密钥和模型参数。
    "ai.eval.write": "提交 AI 评测评分",
    "kb.document.manage": "管理知识库文档",
    "kb.search.test": "知识库检索测试",
    "audit.read": "查看审计日志",
    "admin.manage": "管理员与角色管理",
}

ALL_PERMISSIONS: list[str] = list(PERMISSION_LABELS)


def permission_payload() -> list[dict[str, str]]:
    """给前端使用的权限点列表。"""
    return [
        {"code": code, "label": label}
        for code, label in PERMISSION_LABELS.items()
    ]
