"""开发环境演示数据。

只用于本地/测试联调，生产环境由 APP_ENV 守卫禁止写入。
饭图来自 UI 稿内置示例图集切分，均为演示素材。
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ALL_PERMISSIONS
from app.core.config import settings
from app.core.security import encrypt_phone, hash_password, new_id, phone_lookup_key
from app.db.models import (
    AdminRole,
    AdminRolePermission,
    AdminUser,
    AdminUserRole,
    Like,
    MealPost,
    MediaAsset,
    Recipe,
    RecipeCategory,
    TasteTag,
    User,
)
from app.utils.time import business_day_bounds, now_utc

SEED_AUTHORS = [
    ("u_adao", "阿豆"),
    ("u_xiaoman", "小满"),
    ("u_laozhou", "老周"),
]

SEED_ASSETS = [f"m_seed_{index}" for index in range(1, 7)]


# 权限点集中定义在 app/core/permissions.py，角色只负责把权限点打包。
# 接口用 require_permission("post.review") 逐条声明自己需要的权限。
ROLE_DEFINITIONS = [
    ("super_admin", "超级管理员", ALL_PERMISSIONS),
    (
        "content_operator",
        "内容运营",
        [
            "post.review",
            "post.unpublish",
            "user.read",
            "user.ban",
            "recipe.manage",
            "taste_tag.manage",
            "dashboard.read",
        ],
    ),
    (
        "ai_operator",
        "AI 运营",
        ["ai.log.read", "ai.config.write", "kb.document.manage", "kb.search.test"],
    ),
    # 审计员只读：能看用户列表和审计日志，不能修改任何数据。
    ("auditor", "审计员", ["audit.read", "user.read"]),
]


def _media(asset_id: str, number: int) -> MediaAsset:
    return MediaAsset(
        id=asset_id,
        owner_id="u_seedmedia",
        mime="image/jpeg",
        bytes=180_000,
        width=1200,
        height=1500,
        storage_key=f"seed/food_{number}.jpg",
        thumb_key=f"seed/food_{number}.jpg",
        status="ready",
    )


RECIPES = [
    {
        "id": "r_101",
        "title": "番茄鸡蛋盖饭",
        "cover": "seed/food_4.jpg",
        "minutes": 15,
        "tools": ["wok"],
        "categories": ["recommended", "quick", "few"],
        "servings": 1,
        "main": ["番茄", "鸡蛋", "米饭"],
        "ingredients": [
            {"name": "番茄", "amount": "2 个"},
            {"name": "鸡蛋", "amount": "2 个"},
            {"name": "米饭", "amount": "1 碗（需提前煮好）"},
            {"name": "盐、糖、食用油", "amount": "适量"},
        ],
        "steps": [
            "番茄切块，鸡蛋打散加少许盐。",
            "热锅下油，炒散鸡蛋后盛出。",
            "下番茄炒出汁水，加少许糖和盐。",
            "倒回鸡蛋翻匀，盖在热米饭上。",
        ],
        "preconditions": "需要已有熟米饭；总耗时不含煮饭时间。",
    },
    {
        "id": "r_102",
        "title": "豆角焖面",
        "cover": "seed/food_1.jpg",
        "minutes": 25,
        "tools": ["pot"],
        "categories": ["recommended", "one_pot"],
        "servings": 1,
        "main": ["豆角", "面条"],
        "ingredients": [
            {"name": "豆角", "amount": "200 克"},
            {"name": "鲜面条", "amount": "150 克"},
            {"name": "蒜", "amount": "2 瓣"},
            {"name": "生抽、老抽、盐", "amount": "适量"},
        ],
        "steps": [
            "豆角洗净掰段，蒜切末。",
            "锅中少油炒香蒜末，下豆角翻炒。",
            "加水没过豆角，调味后铺上面条。",
            "盖盖中小火焖至面条熟透，拌匀收汁。",
        ],
        "preconditions": "豆角必须充分熟透后再食用。",
    },
    {
        "id": "r_103",
        "title": "香菇豆腐煲",
        "cover": "seed/food_2.jpg",
        "minutes": 20,
        "tools": ["pot"],
        "categories": ["recommended", "quick", "one_pot", "few"],
        "servings": 1,
        "main": ["豆腐", "香菇"],
        "ingredients": [
            {"name": "嫩豆腐", "amount": "1 盒"},
            {"name": "香菇", "amount": "5 朵"},
            {"name": "葱", "amount": "1 根"},
            {"name": "生抽、蚝油", "amount": "适量"},
        ],
        "steps": [
            "豆腐切块，香菇切片。",
            "锅中放少量油，香菇炒香。",
            "放入豆腐和调味料，加少量水。",
            "小火煮 8 分钟，撒葱出锅。",
        ],
        "preconditions": "需要一口带盖的锅。",
    },
    {
        "id": "r_104",
        "title": "蒜香西兰花",
        "cover": "seed/food_3.jpg",
        "minutes": 12,
        "tools": ["wok"],
        "categories": ["recommended", "quick", "few"],
        "servings": 1,
        "main": ["西兰花", "蒜"],
        "ingredients": [
            {"name": "西兰花", "amount": "1 颗"},
            {"name": "蒜", "amount": "3 瓣"},
            {"name": "盐、食用油", "amount": "适量"},
        ],
        "steps": [
            "西兰花切小朵，冲洗干净。",
            "沸水焯 1 分钟后捞出。",
            "热锅下油炒香蒜末。",
            "下西兰花快速翻炒，加盐出锅。",
        ],
        "preconditions": "需要能烧水的锅和炒锅。",
    },
    {
        "id": "r_105",
        "title": "葱油拌面",
        "cover": "seed/food_5.jpg",
        "minutes": 10,
        "tools": ["pot"],
        "categories": ["recommended", "quick", "one_pot", "few"],
        "servings": 1,
        "main": ["面条", "葱"],
        "ingredients": [
            {"name": "细面条", "amount": "150 克"},
            {"name": "小葱", "amount": "4 根"},
            {"name": "生抽、老抽、糖", "amount": "适量"},
        ],
        "steps": [
            "小葱切段，冷油下锅小火炸香。",
            "葱油中加入生抽、老抽和少许糖。",
            "面条煮熟捞出。",
            "淋葱油拌匀即可。",
        ],
        "preconditions": "需要一口煮面锅。",
    },
    {
        "id": "r_106",
        "title": "微波炉蒸蛋",
        "cover": "seed/food_6.jpg",
        "minutes": 8,
        "tools": ["microwave"],
        "categories": ["recommended", "quick", "one_pot", "few"],
        "servings": 1,
        "main": ["鸡蛋"],
        "ingredients": [
            {"name": "鸡蛋", "amount": "2 个"},
            {"name": "温水", "amount": "100 毫升"},
            {"name": "盐、香油", "amount": "适量"},
        ],
        "steps": [
            "鸡蛋打散，加温水和盐搅匀。",
            "过筛倒入耐热碗。",
            "微波中火 2 分钟，取出静置 1 分钟。",
            "再中火 1 分钟，淋香油。",
        ],
        "preconditions": "需要微波炉和耐热碗。",
    },
    {
        "id": "r_107",
        "title": "青椒肉丝",
        "cover": "seed/food_1.jpg",
        "minutes": 18,
        "tools": ["wok"],
        "categories": ["recommended", "few"],
        "servings": 1,
        "main": ["青椒", "猪肉"],
        "ingredients": [
            {"name": "青椒", "amount": "2 个"},
            {"name": "猪里脊", "amount": "150 克"},
            {"name": "生抽、淀粉", "amount": "适量"},
        ],
        "steps": [
            "肉切丝，用生抽和淀粉抓匀。",
            "青椒切丝。",
            "热锅下油滑炒肉丝至变色盛出。",
            "炒青椒后回锅翻匀。",
        ],
        "preconditions": "猪肉需完全炒熟。",
    },
    {
        "id": "r_108",
        "title": "电饭煲腊肠焖饭",
        "cover": "seed/food_2.jpg",
        "minutes": 30,
        "tools": ["rice_cooker"],
        "categories": ["recommended", "one_pot", "few"],
        "servings": 1,
        "main": ["腊肠", "米饭"],
        "ingredients": [
            {"name": "大米", "amount": "1 杯"},
            {"name": "腊肠", "amount": "1 根"},
            {"name": "青菜", "amount": "2 棵"},
        ],
        "steps": [
            "大米淘洗后放入电饭煲。",
            "腊肠切片铺在米上。",
            "按正常煮饭模式启动。",
            "出锅前放入烫熟的青菜，拌匀。",
        ],
        "preconditions": "需要电饭煲；总耗时含煮饭。",
    },
]


POSTS = [
    {
        "id": "p_1001",
        "author": "u_adao",
        "title": "豆角焖面",
        "review": "一锅到底，豆角软糯、面条吸满汤汁，下班后做这一锅就够了。",
        "source": "self",
        "assets": ["m_seed_1", "m_seed_2", "m_seed_3"],
        "recipe": "r_102",
        "author_recipe": {
            "ingredients": ["豆角 200 克", "鲜面条 150 克", "蒜 2 瓣", "生抽 2 勺"],
            "steps": ["豆角掰段炒香", "加水铺面焖 12 分钟", "拌匀收汁"],
        },
        "avg_price": 22,
        "taste_tags": ["咸鲜", "面食"],
    },
    {
        "id": "p_1002",
        "author": "u_xiaoman",
        "title": "番茄鸡蛋盖饭",
        "review": "酸甜口，十五分钟能上桌。前提是家里有现成的熟米饭。",
        "source": "self",
        "assets": ["m_seed_4"],
        "recipe": "r_101",
        "author_recipe": None,
        "avg_price": 15,
        "taste_tags": ["酸甜"],
    },
    {
        "id": "p_1003",
        "author": "u_laozhou",
        "title": "照烧鸡腿便当",
        "review": "公司楼下这家便当分量稳，鸡腿是现煎的，酱汁偏甜。",
        "source": "takeaway",
        "assets": ["m_seed_5", "m_seed_6"],
        "takeaway_store": "街角便当",
        "author_recipe": None,
        "avg_price": 28,
        "taste_tags": ["咸鲜"],
        "store_lat": 31.2305,
        "store_lng": 121.4737,
        "store_poi_id": "demo-poi-001",
    },
    {
        "id": "p_1004",
        "author": "u_adao",
        "title": "老友牛肉粉",
        "review": "汤头够味，酸笋可以少放一点。店里位置不大，午休要早点去。",
        "source": "dine_in",
        "assets": ["m_seed_1"],
        "dine_in_address": "演示路 12 号 · 老友粉店",
        "author_recipe": None,
        "avg_price": 26,
        "taste_tags": ["香辣", "汤羹"],
        "store_lat": 31.2286,
        "store_lng": 121.469,
        "store_poi_id": "demo-poi-002",
    },
    {
        "id": "p_1005",
        "author": "u_xiaoman",
        "title": "香菇豆腐煲",
        "review": "少洗一个锅的快乐。豆腐先煎一下更不容易碎。",
        "source": "self",
        "assets": ["m_seed_2", "m_seed_4"],
        "recipe": "r_103",
        "author_recipe": {
            "ingredients": ["嫩豆腐 1 盒", "香菇 5 朵", "葱 1 根"],
            "steps": ["豆腐切块", "香菇炒香后加豆腐", "小火煮 8 分钟"],
        },
        "avg_price": 18,
        "taste_tags": ["清淡"],
    },
    {
        "id": "p_1006",
        "author": "u_laozhou",
        "title": "蒜香西兰花",
        "review": "先焯水再炒，颜色会好看很多，也不容易夹生。",
        "source": "self",
        "assets": ["m_seed_3"],
        "recipe": "r_104",
        "author_recipe": None,
        "avg_price": 12,
        "taste_tags": ["清淡"],
    },
    {
        "id": "p_1007",
        "author": "u_adao",
        "title": "葱油拌面",
        "review": "十分钟解决。葱一定要小火慢慢炸，糊了就苦。",
        "source": "self",
        "assets": ["m_seed_5"],
        "recipe": None,
        "author_recipe": {
            "ingredients": ["细面条 150 克", "小葱 4 根", "生抽 2 勺", "糖 半勺"],
            "steps": ["冷油小火炸葱", "调好酱汁", "煮面拌匀"],
        },
        "avg_price": 10,
        "taste_tags": ["咸鲜", "面食"],
    },
    {
        "id": "p_1008",
        "author": "u_xiaoman",
        "title": "青椒肉丝盖饭",
        "review": "楼下小馆的青椒肉丝，肉给得不吝啬，米饭稍微硬一点。",
        "source": "takeaway",
        "assets": ["m_seed_6", "m_seed_1"],
        "takeaway_store": "楼下小馆",
        "author_recipe": None,
        "avg_price": 24,
        "taste_tags": ["香辣"],
        "store_lat": 31.2318,
        "store_lng": 121.4752,
        "store_poi_id": "demo-poi-003",
    },
    {
        "id": "p_1009",
        "author": "u_laozhou",
        "title": "微波炉蒸蛋",
        "review": "加班回家只想吃口热的，两个蛋加温水，八分钟搞定。",
        "source": "self",
        "assets": ["m_seed_4"],
        "recipe": None,
        "author_recipe": None,
        "avg_price": 6,
        "taste_tags": ["清淡"],
    },
]

LIKE_COUNTS = {
    "p_1001": 11,
    "p_1002": 9,
    "p_1003": 8,
    "p_1004": 6,
    "p_1005": 5,
    "p_1006": 4,
    "p_1007": 3,
    "p_1008": 2,
    "p_1009": 0,
}


# 口味标签的初始字典，与旧前端页面里展示的 9 个选项完全一致。
# 顺序即展示顺序，写入 sort_order；以后运营调整顺序或停用标签只需改数据库。
TASTE_TAG_NAMES = [
    "清淡",
    "正常",
    "香辣",
    "酸甜",
    "咸鲜",
    "油炸",
    "烧烤",
    "汤羹",
    "面食",
]


async def seed_taste_tags(db: AsyncSession) -> None:
    """补齐口味标签字典。

    为什么单独做成一个函数、并且在应用启动时无条件调用：
    1. 字典是基础数据，新环境第一次启动就必须有，否则前端拿不到任何标签；
    2. 只插入“缺失的”标签，不覆盖已有记录，避免把运营在后台改过的顺序或启用状态冲掉；
    3. 演示数据函数可能因为“库里已有用户”提前返回，所以不能把字典初始化只放在它里面。
    """
    existing = set((await db.scalars(select(TasteTag.name))).all())
    added = False
    for order, name in enumerate(TASTE_TAG_NAMES, start=1):
        if name in existing:
            continue
        db.add(TasteTag(name=name, sort_order=order, enabled=True))
        added = True
    if added:
        await db.commit()


async def seed_demo_data(db: AsyncSession) -> None:
    # 先补字典，再判断演示用户是否存在：
    # 字典属于基础数据，即使演示数据已经初始化过，也要保证它是最新的。
    await seed_taste_tags(db)
    exists = await db.scalar(select(func.count(User.id)))
    if exists:
        return

    users: list[User] = []
    for index, (user_id, nickname) in enumerate(SEED_AUTHORS, start=1):
        users.append(
            User(
                id=user_id,
                phone_encrypted=encrypt_phone(f"1390000000{index}"),
                phone_lookup_key=phone_lookup_key(f"1390000000{index}"),
                nickname=nickname,
            )
        )
    # 图片资产的系统持有者，状态非 active，不能登录。
    users.append(
        User(
            id="u_seedmedia",
            phone_encrypted=encrypt_phone("13000000000"),
            phone_lookup_key=phone_lookup_key("13000000000"),
            nickname="演示素材",
            status="system",
        )
    )
    for index in range(1, 13):
        phone = f"139100000{index:02d}"
        users.append(
            User(
                id=f"u_like{index}",
                phone_encrypted=encrypt_phone(phone),
                phone_lookup_key=phone_lookup_key(phone),
                nickname=f"饭友{index}",
            )
        )
    db.add_all(users)
    # 先落库用户，保证后续饭帖、点赞的外键在 PostgreSQL 下一定已存在。
    await db.flush()

    db.add_all([_media(asset_id, number) for number, asset_id in enumerate(SEED_ASSETS, start=1)])

    for item in RECIPES:
        db.add(
            Recipe(
                id=item["id"],
                title=item["title"],
                cover_url=item["cover"],
                total_minutes=item["minutes"],
                tool_codes=item["tools"],
                category_codes=item["categories"],
                servings=item["servings"],
                main_ingredients=item["main"],
                ingredients=item["ingredients"],
                steps=item["steps"],
                preconditions=item["preconditions"],
                content_origin="platform",
                validation_status="tested",
                status="published",
            )
        )
        for code in item["categories"]:
            db.add(RecipeCategory(id=new_id("rc"), recipe_id=item["id"], code=code))
    # 菜谱先落库，饭帖的 platform_recipe_id 外键依赖它。
    await db.flush()

    day_start, day_end = business_day_bounds()
    now = now_utc()
    usable_window = max((now - day_start).total_seconds(), 60)
    for index, item in enumerate(POSTS):
        # 保证发布时间落在“今天”且不晚于当前时刻。
        offset_seconds = int(usable_window * (index + 1) / (len(POSTS) + 1))
        published = min(day_start + timedelta(seconds=offset_seconds), now - timedelta(seconds=1))
        if published < day_start:
            published = day_start
        db.add(
            MealPost(
                id=item["id"],
                author_id=item["author"],
                title=item["title"],
                review=item["review"],
                source=item["source"],
                image_asset_ids=item["assets"],
                author_recipe=item.get("author_recipe"),
                platform_recipe_id=item.get("recipe"),
                takeaway_store=item.get("takeaway_store"),
                dine_in_address=item.get("dine_in_address"),
                avg_price=item.get("avg_price"),
                taste_tags=item.get("taste_tags", []),
                store_lat=item.get("store_lat"),
                store_lng=item.get("store_lng"),
                store_poi_id=item.get("store_poi_id"),
                coarse_lat=31.23 if index < 5 else None,
                coarse_lng=121.47 if index < 5 else None,
                coarse_area="演示商圈" if index < 5 else None,
                status="published",
                published_at=published,
            )
        )
    # 饭帖先落库，点赞的 post_id 外键依赖它。
    await db.flush()

    like_rows = []
    for post_index, item in enumerate(POSTS):
        count = LIKE_COUNTS[item["id"]]
        for liker_index in range(1, 13):
            active = liker_index <= count
            like_rows.append(
                Like(
                    id=f"l_{post_index + 1}_{liker_index}",
                    account_id=f"u_like{liker_index}",
                    post_id=item["id"],
                    active=active,
                    risk_status="valid",
                )
            )
    db.add_all(like_rows)
    await db.commit()


async def seed_admin_data(db: AsyncSession) -> None:
    """初始化后台角色、权限点和首个管理员。

    幂等：重复启动只补齐缺失的角色或权限，不会重复插入。
    管理员密码只从环境变量 ADMIN_INITIAL_PASSWORD 读取；
    未配置时不创建账号，代码中不写死任何默认密码。
    """
    roles = {role.code: role for role in (await db.scalars(select(AdminRole))).all()}

    for code, name, permissions in ROLE_DEFINITIONS:
        role = roles.get(code)
        if role is None:
            role = AdminRole(id=f"role_{code}", code=code, name=name)
            db.add(role)
            await db.flush()
            roles[code] = role

        existing = set(
            (
                await db.scalars(
                    select(AdminRolePermission.permission_code).where(
                        AdminRolePermission.role_id == role.id
                    )
                )
            ).all()
        )
        for permission in permissions:
            if permission not in existing:
                db.add(
                    AdminRolePermission(
                        id=new_id("arp"),
                        role_id=role.id,
                        permission_code=permission,
                    )
                )
    await db.flush()

    if not settings.admin_initial_password:
        # 没有配置初始密码就不创建管理员，避免出现“人人皆知的默认账号”。
        await db.commit()
        return

    admin = await db.scalar(
        select(AdminUser).where(AdminUser.username == settings.admin_initial_username)
    )
    if admin is None:
        admin = AdminUser(
            id=new_id("adm"),
            username=settings.admin_initial_username,
            password_hash=hash_password(settings.admin_initial_password),
            display_name="超级管理员",
            status="active",
        )
        db.add(admin)
        await db.flush()

    super_role = roles["super_admin"]
    has_role = await db.scalar(
        select(AdminUserRole).where(
            AdminUserRole.admin_id == admin.id,
            AdminUserRole.role_id == super_role.id,
        )
    )
    if has_role is None:
        db.add(
            AdminUserRole(
                id=new_id("aur"),
                admin_id=admin.id,
                role_id=super_role.id,
            )
        )
    await db.commit()
