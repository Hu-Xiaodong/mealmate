"""导入批次、后台任务与菜谱来源字段的数据模型测试。"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import ImportBatch, IngestionJob, Recipe
from app.main import app


async def test_import_batch_job_and_recipe_source(client) -> None:
    factory = app.state.test_session_factory
    async with factory() as db:
        batch = ImportBatch(
            id="imp_test_1",
            source_type="howtocook",
            source_uri="https://github.com/Anduin2017/HowToCook",
            source_ref="58c1b9a",
            status="running",
        )
        job = IngestionJob(
            id="job_test_1",
            batch_id=batch.id,
            job_type="parse_repository",
            payload={"root": "HowToCook"},
        )
        db.add_all([batch, job])
        await db.flush()

        recipe = Recipe(
            id="rcp_import_1",
            title="导入测试菜",
            cover_url="",
            total_minutes=None,
            tool_codes=[],
            category_codes=[],
            servings=1,
            main_ingredients=["盐"],
            ingredients=[{"name": "盐", "amount": "2g"}],
            steps=["炒熟"],
            description="来源简介",
            tips="来源提示",
            difficulty="★",
            tags=["素菜"],
            source_type="howtocook",
            source_uri="dishes/vegetable_dish/导入测试菜.md",
            source_checksum="a" * 64,
            source_license="Unlicense",
            import_batch_id=batch.id,
            source_meta={"category": "vegetable_dish"},
        )
        db.add(recipe)
        await db.commit()

    async with factory() as db:
        saved_recipe = await db.scalar(select(Recipe).where(Recipe.id == "rcp_import_1"))
        assert saved_recipe is not None
        # 没写时长就是空值，不能变成 0。
        assert saved_recipe.total_minutes is None
        assert saved_recipe.source_type == "howtocook"
        assert saved_recipe.source_license == "Unlicense"
        assert saved_recipe.import_batch_id == "imp_test_1"
        assert saved_recipe.source_meta == {"category": "vegetable_dish"}

        saved_batch = await db.get(ImportBatch, "imp_test_1")
        assert saved_batch is not None and saved_batch.stats == {}
        saved_job = await db.get(IngestionJob, "job_test_1")
        assert saved_job is not None and saved_job.attempts == 0

    # 同一来源的同一个文件只能对应一条菜谱，重复导入必须在数据库层被拦住。
    async with factory() as db:
        duplicate = Recipe(
            id="rcp_import_2",
            title="重复菜谱",
            cover_url="",
            tool_codes=[],
            category_codes=[],
            ingredients=[{"name": "盐"}],
            steps=["炒熟"],
            source_type="howtocook",
            source_uri="dishes/vegetable_dish/导入测试菜.md",
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async with factory() as db:
        count = len(
            (
                await db.scalars(
                    select(Recipe).where(Recipe.source_uri == "dishes/vegetable_dish/导入测试菜.md")
                )
            ).all()
        )
        assert count == 1
