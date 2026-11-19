from pathlib import Path
import re
import shutil
import json

ROOT = Path('E:/项目/thinkingDiscussion/docs')
DRAFTS = ROOT / 'prd-drafts'
VIZ = Path('C:/Users/Administrator/.codex/visualizations/2026/10/19/01a15375-73da-71c0-aed2-8be4bc541411')

# 保留可评审的来源章节，只在汇总时统一术语和原型边界，避免不同章节给出相反要求。
overview = (DRAFTS / '01-overview.md').read_text(encoding='utf-8')
features = (DRAFTS / '03-functional.md').read_text(encoding='utf-8')
engineering = (DRAFTS / '04-engineering-acceptance.md').read_text(encoding='utf-8')
decisions = (DRAFTS / '05-decisions-sources.md').read_text(encoding='utf-8')
features = features.replace('原型说明是演示协议；正式文本、版本与记录方式需上线前确认', '原型只勾选“已了解本次为演示登录”，不提供正式协议；正式版本必须有可读的真实协议、版本及同意记录')
features = features.replace('手机号格式、协议勾选等前置校验通过后发起；请求中不可重复点击', '正式版在手机号格式、协议等前置校验通过后发起；原型仅模拟取码，勾选项在最终登录前校验；请求中不可重复点击')
features = features.replace('勾选演示协议', '勾选已了解演示')
features = features.replace('冷却期间重进页面保持剩余秒数', '正式版冷却期间重进页面保持剩余秒数；原型取消登录会清表单，重新打开须重新取演示码，不提供短信安全限流的证明')
features = features.replace('原型以明确演示提示为准', '原型点击退出后提示未发布草稿已清除；正式版按前述方案提供取消机会')

project_rules = '''### 4.2.1 本项目代码与国际化约束

所有面向项目协作者的说明使用中文。修改前说明思路、范围和验证；优先复用公共组件，页面个性化通过组合或配置实现；修改限于已授权范围。可复用逻辑抽为公共函数，新增函数使用中文注释解释作用与原因，清理废弃代码。正式提交需要适用的静态检查、构建、风险用例和真机回归记录。

若正式代码沿用本项目 `src/lang/zh`、`src/lang/en` 的语言包结构，必须同步维护完全一致的key路径；顶层命名空间内使用camelCase，检索避免冲突；新增内容追加到对应模块末尾，不格式化无关历史内容。按本项目约定，英文包新增value只在中文前拼接EN，不自行翻译；不存在的模块需同步创建并在中英文index汇总。页面按钮、空态、错误、校验、Tab和提示均使用翻译调用，不新增中文key或`$t('中文文案')`。若选用其他移动框架，应在技术评审中明确对应的文案集中管理映射，不能误称当前尚不存在Vue工程。可运行时执行项目构建；不能运行时记录具体缺失环境，不把未执行写成通过。

'''
engineering = engineering.replace('### 4.3 性能、兼容与可观测性', project_rules + '### 4.3 性能、兼容与可观测性')
# 全篇只保留一份带建议值的待确认清单，以免评审时出现重复编号或不一致的默认值。
engineering = engineering.split('### 5.4 本章待确认项汇总')[0]
trace = '''### 5.4 需求与验收追溯

| 功能范围 | 主要验收编号 | 验收环境 |
|---|---|---|
| 四Tab与公开浏览 | AC-001至002、023至026 | 原型及正式环境；真实位置仅正式 |
| 登录及一次续办 | AC-003至015 | 模拟登录原型；短信与账户隔离正式 |
| 统一小图收藏 | AC-016至022 | 尺寸/本地交互原型；跨设备与失效正式 |
| 热榜与食材可信度 | AC-027至037 | 展示原型；日界、有效赞及治理正式 |
| 快手菜谱 | AC-036至039 | 标签/结构原型；时间试做与内容审核正式 |
| 相册轮播与手动切图 | AC-040至049 | 浏览器交互、移动真机与前后台 |
| 三来源发布 | AC-050至058 | 表单与模拟流程原型；上传/幂等/审核正式 |
| AI提示、上下文与语音 | AC-059至070 | 入口/提示/示例交互原型；真实服务正式 |
| 工程安全、兼容与交付 | AC-071至080 | 构建、真实集成、真机和上线评审 |

测试用例应附需求编号或所属功能，测试结果需要证据和构建版本。上述区间是索引，不表示不同模块之间没有交叉，也不意味着整段用例均可在原型完成。

'''
full = '\n\n'.join([overview, features, engineering, trace, decisions])
target = ROOT / '今天吃啥_PRD_V1.0.0.md'
target.write_text(full, encoding='utf-8')
pending = decisions.split('### 5.6')[0].replace('### 5.5 全篇待确认项与默认建议', '# 今天吃啥需求待确认清单\n\n版本 V1.0.0 · 2026-10-30')
(ROOT / '今天吃啥_PRD_V1.0.0_待确认项.md').write_text(pending, encoding='utf-8')
(ROOT / 'assets').mkdir(exist_ok=True)
for name in ('mine-guest.png', 'login.png', 'favorites.png'):
    shutil.copy2(VIZ / 'output/login-check' / name, ROOT / 'assets' / name)

# 检查编号唯一性、表格列数和图像引用，避免详文规模较大时产生无法直接评审的格式错误。
ids = re.findall(r'^\| (REQ-[A-Z0-9-]+) \|', full, re.M)
acs = re.findall(r'^\| (AC-\d+) \|', full, re.M)
issues = []
expected = None
for number, line in enumerate(full.splitlines(), 1):
    if line.startswith('|'):
        columns = len(re.split(r'(?<!\\)\|', line)) - 2
        if expected is None:
            expected = columns
        elif columns != expected:
            issues.append({'line': number, 'expected': expected, 'actual': columns})
    else:
        expected = None
assert len(ids)==len(set(ids)), '需求编号重复'
assert len(acs)==80 and len(set(acs))==80, '验收编号不完整'
assert full.count('```')%2==0, '代码围栏未闭合'
print(json.dumps({'bytes': target.stat().st_size, 'requirements':len(ids), 'acceptance':len(acs), 'tableIssues':issues, 'mermaid':full.count('```mermaid')},ensure_ascii=False))
