# Kotonoha 架构分层与重构实施计划

> **状态：Phase 2/#14 主链路已落地，Phase 3/4 已完成并完成审查收口，Phase 5/6 已完成**
>
> 这份计划服务于仓库作者的长期重构。它先固定行为和边界，再迁移实现；不接受“发现一个 case 就在现有协调器加一个 if”作为完成方式。
>
> Phase 0-5 的章节保留实施历史；其中出现的旧路径、旧类名和迁移期兼容层不是当前代码入口。

## 目标

将 Kotonoha 改造成职责清晰、强类型、可验证、可持续演进的桌面歌词系统：

- `app/` 明确编排、能力契约、工作流和资源生命周期；
- `lyrics/`、`playback/`、`display/`、`config/` 等 feature package 各自拥有稳定值类型、纯规则和对应的外部适配；
- `ui/` 只负责 Qt 展示、输入绑定和把用户操作转成 typed intent；
- `platform/` 负责 compositor/toolkit 事实、能力探测和平台资源生命周期；
- 不用泛化的 `domain/`、`infrastructure/`、`ports/`、`presentation/` 或 `composition/` 包隐藏 owner；
- 每个行为由 policy、状态机、result type 和测试共同定义。

## 不做的事

- 不一次性重写全部 `src/kotonoha`。
- 不先按文件大小机械拆分 `mpris.py`、`ui/settings/dialog.py`；Overlay 目录拆分必须服从 UI 生命周期和协作者边界。
- 不在行为契约未确定前改变 provider precedence、置信度阈值或用户可见状态。
- 不把已有 PR 的每个例外原样复制到新模块；先判断它属于稳定行为、实现补丁还是错误行为。
- 不用扩大 `Any`、`cast`、`type: ignore` 或宽 Protocol 来“让 ty 通过”。
- 不在同一个迁移 PR 混合行为变化、平台 lifecycle、UI 视觉和 packaging。

## 证据边界

### 行为矩阵

- [歌词 PR 行为矩阵](../specs/2026-08-23-lyrics-pr-behavior-matrix.md)
- [Overlay PR 行为矩阵](../specs/2026-08-23-overlay-pr-behavior-matrix.md)
- [行为等价性与 corner case 保护](../specs/2026-08-23-behavior-equivalence-policy.md)

矩阵只记录当前代码、测试和最近提交实际产生的行为，不是目标行为清单。目标 policy 以本计划和设计规格
为准；观察到的行为必须重新判断是目标行为、实现偶然性，还是应该删除的复杂度。

### 关键观察

- `#26 -> #42 -> #64` 暴露 raw title 被清洗后丢失 gate 证据；这是数据模型边界问题。
- `#27 -> #31` 暴露 platform Protocol、capability probe、registry 和 settings 之间的 owner/语义问题；这是操作契约问题。
- `#30` 在抽象迁移后连续修复 output rebinding、deferred callback、失败重建、blur release 和 stale geometry；这是生命周期状态机缺失问题。
- `#49 -> #50 -> #57 -> #61 -> #63` 暴露 response/path/task/D-Bus/WebSocket 等边界预算和 cancellation owner 问题。
- 当前 `prefer_best_lyrics` 会触发 resolver 的并发 source fetch；它与 ordered source plan 是两种可选策略，必须由配置明确选择。

## 目标代码边界与目录拆分

这里参考 `bilihud/docs/architecture/module-boundaries.md` 的 feature-first 取向，但不机械复制业务名称。
目录表达的是 owner，而不是抽象层口号：一个 feature package 可以同时拥有自己的稳定值类型、纯规则、
解析器和具体外部适配；`app/` 只编排这些能力，不把它们重新包装成一个泛化的 `infrastructure/`。
因此目标结构中不建立通用的 `domain/`、`infrastructure/`、`ports/`、`presentation/`、`composition/` 或
`shared/` 包。

早期迁移期间曾允许用窄的兼容入口承接 import；最终落地目录如下，当前不保留这些迁移层，
也不是早期的 coordinator/parsers 目标草图：

```text
src/kotonoha/
  app/                         # workflow、生命周期、能力契约和 composition wiring
    composition.py             # 唯一的 concrete adapter object graph 组装点
    application_controller.py  # 启动/停止应用服务和 typed intent routing
    components.py              # controller 的窄 port bundle
    config_service.py          # 应用范围唯一 Config owner、即时持久化和配置变更
    config_merge.py            # Settings changed-field 的纯合并变换
    display_coordinator.py     # DisplayFrame projection、clock tick 和 publisher lifecycle
    lifecycle.py               # TaskSupervisor 和取消/等待语义
    restart.py                 # 进程重启边界
    services.py                # 运行时配置应用等 application service
    settings_port.py           # Settings dialog 的 application-facing ports
    source_contracts.py        # live source 的窄 Protocol 与值对象
    source_gate.py             # standalone/external/Cider source ownership
    source_matching.py         # candidate 匹配纯规则
    source_registry.py         # candidate/clock 登记生命周期

  playback/                    # 播放功能的 canonical values 和 identity rule
    models.py                  # PlaybackStatus、TrackIdentity、PlaybackObservation
    identity.py                # 唯一 track identity/offset key 规则

  providers/                   # 外部播放器、网络和第三方协议适配器
    mpris.py                   # MPRIS facade
    mpris_playback.py          # D-Bus session、订阅、poll 和稳定化生命周期
    mpris_resolution.py        # MPRIS resolver 会话
    mpris_lyrics.py            # MPRIS lyric generation 与 workflow 编排
    mpris_display.py           # MPRIS sample 到 display 的绑定
    mpris_track.py             # raw metadata 解析和 track 稳定器
    mpris_session.py           # dbus-fast session boundary
    mpris_adapter.py           # MPRIS playback adapter
    mpris_timeline.py          # MPRIS position calibration
    player_selection.py        # player discovery 和 selection policy
    cider_client.py            # Cider HTTP session、响应边界和可选 token
    cider_api.py               # Cider 低频校准与按 track generation 的歌词任务

  lyrics/                     # 歌词功能的 contracts、解析、匹配、source/cache adapter
    models.py                  # LyricDocument、LyricLine、LyricWord
    artifact.py                # provider-neutral LyricsArtifact
    adapter.py                 # artifact -> canonical document adapter
    title_grammar.py           # title/artist decomposition、qualifier 和 normalizer
    artist_grammar.py          # artist tokenization and performer variants
    title_queries.py           # provider query variants
    player_title_grammar.py    # player/browser title decoration grammar
    match.py                   # MatchEvidence、confidence 和 ranking policy
    lrc_parser.py              # LRC parser
    krc_parser.py              # KRC parser
    yrc_parser.py              # YRC parser
    sources.py                 # local/exact/network source contracts
    network_sources.py         # network source lifecycle adapter
    local.py                   # sidecar/embedded file adapter
    live_source.py             # live external source adapter
    resolver.py                # source policy、缓存与 in-flight 去重
    workflow.py                # generation-owned SourcePlan 执行和结果发布
    cache/                      # bounded SQLite/file cache boundary
      models.py                 # typed cache keys, entries, modes, and results
      __init__.py               # SQLite persistence and cache lifecycle
    protocol.py                # generic adapter v1 boundary decoder
    payload.py                 # bounded network payload readers
    translation.py             # timestamp/positional translation transforms

  display/                    # 纯展示模型和时间轴规则
    models.py                  # DisplayState、DisplayFrame 和 display diagnostics
    presentation.py            # DisplayEngine：唯一展示策略 owner
    timeline.py                # line selection、offset、interlude 和 clock-independent display facts
    karaoke.py                 # line/word progress 和 font-fit policy 的纯部分
    rules.py                   # current/interlude/sweep 纯规则
    layout.py                  # 无 Qt 的字体/宽度 fit policy
    text.py                    # display-only text transformation
    contracts.py               # adapter-specific display publication Protocol

  config/                     # typed configuration 和持久化边界
    models.py                  # Config 和 constraints
    schema.py                  # Settings 字段与页面分组的唯一声明
    store.py                   # JSON decode/validate/atomic persistence

  file_access.py              # bounded regular-file boundary shared by config/local

  platform/                   # toolkit-neutral contracts 与桌面/native adapters
    overlay_contracts.py       # capability、geometry、output、drag 和 operation result
    window_platform.py         # capability selection/registry
    qt_host.py                 # generic Qt window adapter
    qt_window.py               # regular/overlay window factory
    layer_shell.py             # Layer Shell/niri adapter
    native.py / detect.py      # native bridge loading 和 environment probe

  ui/                         # Qt presentation，按 user-facing responsibility 分组
    overlay/                   # QWidget window、KaraokeLabel、state 和 publisher
    settings/                  # dialog、form state 和 settings pages
  clock.py                    # smooth local media clock
  icons.py / leaf_icon.py     # Qt resource/rendering helpers
  i18n.py / strings/           # presentation text and language binding
  players.py                  # player descriptor and browser title facts
  tray.py                     # tray menu、icon selection 和 commands

  receiver.py                 # generic adapter WebSocket receiver
  main.py                     # process entry、Qt/qasync event loop 和 last-resort cleanup
```

`app/composition.py` 是唯一的组合根：它可以 import concrete adapters，并把同一份 config、cache、platform
capability 和 workflow wiring 组装起来；`app/` 下的 workflow 与 capability contract 不能反向依赖
Qt、aiohttp、dbus-fast、native bridge 或具体 source adapter。`main.py` 只负责进程级启动和事件循环，
不承载歌词、播放器或 Overlay 的业务决策；`AppController` 只接收显式必需依赖，不负责 concrete
adapter 的默认创建。

| Owner | 负责 | 可以依赖 | 不得依赖 |
| --- | --- | --- | --- |
| `app/` workflow | use case、generation、source plan、intent routing、task/resource lifecycle | feature contract、platform contract、标准库 | Qt presentation、network/dbus/native concrete adapter；`composition.py` 之外不得组装实现 |
| feature package contracts | `lyrics`/`playback`/`display`/`config` 的 typed values、状态、错误和纯规则 | 标准库及其他稳定 feature contract | Qt、aiohttp、dbus-fast、文件/平台 API、raw third-party object |
| feature package adapters | 网络、文件、D-Bus 和第三方数据的解析/验证/归一化 | 本 feature contract、外部库、命名 capability contract | UI 决策、跨 feature workflow state |
| `ui/` | QWidget、dialog、tray、输入翻译和 state binding | app contract、feature values、Qt | 网络/session/cache、配置持久化、具体平台实现和 native bridge |
| `platform/` | compositor/toolkit facts、capability probe、surface/output/drag/native resource | toolkit/native API、toolkit-neutral platform contract | 歌词/provider policy、UI workflow 和应用状态决策 |
| `main.py` | CLI、Qt/qasync event loop、last-resort cleanup | `app/composition.py`、application controller、Qt/qasync | 具体业务 policy、feature 内部状态和 concrete graph assembly |

### 边界规则

- feature contract 只依赖标准库和其他稳定 feature contract；第三方对象必须在 feature adapter
  边界解析、验证并归一化后才能进入 workflow。
- application workflow 只依赖命名的 capability contract；协议应放在所属 workflow 或 feature
  旁边，例如 `lyrics/workflow.py` 的 source capability，而不是集中到 `ports/`。
- `ui/` 可以依赖 `app` contract、feature value 和 Qt，但不能创建 network/session/cache，也不能
  自己读取 desktop name、Qt platform name 或 native bridge。
- `platform/overlay_contracts.py` 只描述 toolkit-neutral capability/result；Qt、Wayland、Layer Shell
  和 `ctypes` 只出现在 `platform` adapter 内。surface、blur、input、output、drag 的失败必须返回
  `Rejected`/`Unavailable`/`Degraded` 等实际结果及可展示 reason。
- application 是异步 task、session、server 和 surface lifecycle 的 owner；UI signal 只提交 intent，
  不创建无 owner 的 background task。
- 配置只由 `config/` 持有一套 typed model；旧的 root `config.py`、`config_store.py`、
  `config_schema.py` 和 `state.py` 已删除，不作为当前导入入口。
- package 内没有独立责任的转发模块不应被创建；目录拆分必须同时带 public contract、owner、输入/输出
  语义和对应测试。

### 历史迁移映射（仅供追溯）

| 当前实现 | 目标 owner | 目标位置 | 边界意图 |
| --- | --- | --- | --- |
| `controller.py` | 应用组合和 workflow wiring | `app/application_controller.py`、`app/services.py` 及各 coordinator | controller 不再拥有 MPRIS、歌词解析、Overlay 或 Settings policy |
| `providers/mpris*.py`、`players.py` | Playback external adapter/contracts | `providers/`、`playback/` | D-Bus/raw metadata 只在 adapter 内解析；poll/subscription task 归 application coordinator；不为目录形式机械搬运 provider |
| `providers/player_selection.py` | Playback selection policy | `providers/player_selection.py` | runtime 和 Settings 共用同一 typed descriptor/policy；provider 适配器不为目录形式机械搬运 |
| `providers/gate.py`、`receiver.py` | Cider adapter + source ownership workflow | `app/source_gate.py`、`receiver.py`、`lyrics/protocol.py` | legacy gate 已删除；WebSocket/HTTP payload 先归一化，active source 由 ownership coordinator 决定 |
| `platform/qt_host.py` | Qt WindowHost presentation adapter | `platform/qt_host.py`、`platform/qt_window.py` | Qt widget/native handle translation 不进入 app 或 feature contract |
| `lyrics/*.py` | Lyrics feature contracts、parsers 和 adapters | `lyrics/models.py`、`lyrics/title_grammar.py`、`lyrics/match.py`、`lyrics/*_parser.py`、`lyrics/sources.py`、`lyrics/network_sources.py`、`lyrics/live_source.py` | provider 细节留在 lyrics feature；source contract 不依赖 display 或 concrete HTTP client |
| `model.py` | 按语义拆分的 feature values | `lyrics/models.py`、`playback/models.py`、`display/models.py`、`app/source_contracts.py` | 不保留一个跨 feature 的万能 model module |
| `clock.py`、`karaoke.py` | Playback observation / display rules | `clock.py`、`display/timeline.py`、`display/karaoke.py` | 纯规则留在 owner feature，时间源选择和发布由 app coordinator 负责 |
| `overlay/` | Overlay Qt presentation | `ui/overlay/`、`platform/` | QWidget 只渲染 `DisplayFrame`、翻译输入和显示平台结果；应用编排由 `AppController` 持有 |
| `dialog.py`、`tray.py`、`icons.py`、`leaf_icon.py` | Qt presentation | `ui/settings/`、`tray.py`、根级资源 helper | UI 通过 app capability 和 typed intent 工作，不直接保存配置或探测平台 |
| `config.py`、`config_store.py`、`config_schema.py` | Config model/store/schema | `config/models.py`、`config/store.py`、`config/schema.py` | JSON decode、validation、atomic persistence 只有一个 owner；`kotonoha.config` 由最终 package 提供 |

目录名不是目标本身。每个模块必须有明确的 public contract、输入输出、owner 和测试；如果某个模块
只有转发函数而没有独立责任，不应为了“分层”创建它。

## 分阶段实施

### Phase 0：行为盘点与目标决策

**目的**：把当前实现的行为与新设计的目标行为分开，先完成 policy 决策，再开始代码迁移。

- [x] 将歌词矩阵和 Overlay 矩阵中的行为标记为 `Retain`、`Redefine` 或 `Remove`；`Retain` 必须有用户价值和明确 owner，不能因为当前存在就默认保留。逐条登记见两份行为矩阵的 Phase 0 决策登记。
- [x] 为每条 `Retain` 行为补一个 public contract test；测试输入使用真实形状的 fake，不读取源代码字符串。逐条入口见 `docs/superpowers/specs/2026-08-23-phase0-evidence-register.md`。
- [x] 建立 `BehaviorCase[TInput, TPublicOutput]` typed corpus，先收录 title、LRC/YRC/KRC parser、match、display、gate、clock 和 platform 的代表性回归样本。当前入口为 `tests/behavior_corpus.py` 与 `tests/behavior_runtime_corpus.py`，provider/source workflow 的 target corpus 在迁移对应 owner 时继续扩充。
- [x] 为每个语义 grammar/parser rule 建立正向 case、近邻负向 case 和 rule id；expected 只保存 canonical public result，不保存私有正则实现细节。登记和门禁见 `tests/behavior_rule_inventory.py` 与 `tests/test_behavior_corpus.py`。
- [x] 用当前实现生成冻结 baseline，并实现新旧实现的 differential comparator；未登记差异不得合并。当前 comparator 和冻结结果位于 `tests/behavior_corpus.py`。
- [x] 建立 `BehaviorChangeRecord` 流程：任何有意改变必须同时写明 case、旧行为、新目标、用户影响和新的契约测试。模板和 #62 拆分记录位于 `docs/superpowers/behavior-changes/`。
- [x] 建立并执行当前实现的 golden baseline（场景目录和逐场景入口见 `docs/superpowers/specs/2026-08-23-kotonoha-golden-scenarios.md` 与 `docs/superpowers/specs/2026-08-23-phase0-evidence-register.md`）；`target` 场景只冻结 Phase 1 契约，不伪装成当前实现：
  - MPRIS queue cumulative length/position；
  - title 与 artist 在切歌时混合；
  - raw title 含 uploader/版本/频道噪声；
  - exact song id 成功/失败/禁用 provider；
  - sidecar/embedded/network precedence；
  - network timeout、HTTP 200 错 payload、body/decompression over limit；
  - caller cancellation 与 owner shutdown；
  - Cider selected/unselected、disconnect、stale generation；
  - word timing、无空格文字、interlude、无歌词、font fit；
  - output unplug/replug、rebind failure、closed callback、drag failure。
- [x] 审核设计规格 §5.4 的默认 policy，并登记作者最终决策：
  1. 来源优先级为“用户手动选择、sidecar、embedded、播放器精确歌曲 ID、当前选中的
     Cider 会话、配置的网络来源”；自动 cache 只加速所属来源，不改变来源优先级。
  2. `ordered_first` 与 `best_confidence` 都是公开 policy，默认使用 `best_confidence`，因为
     默认优先得到匹配质量最高的歌词；`ordered_first` 作为可选策略，来源顺序仍由用户配置。
  3. `EXACT/HIGH` 可以作为自动结果；`MEDIUM` 先等待其他来源，只有没有更可靠结果时才作为
     候选显示。自动流程不持久化 `MEDIUM`，用户确认后可以将其保存为本地歌词。
  4. 用户手动选择的结果属于“用户确认歌词”，优先于所有自动来源；清除手动选择后才恢复
     自动解析。它不要求新增一种文件格式，普通 cache 命中也不自动获得该优先级。
  5. 展示解析状态使用 `NoTrack/Resolving/LyricsAvailable/LyricsNotFound`；界面文案使用
     “找不到歌词”。`Transition` 和 `Interlude` 是当前展示内容或时间轴推导，不建立
     `Finished` 状态。
  6. Cider 断线或 Position 暂不可用时，已经找到的歌词不清空，clock 回退到 MPRIS；短暂空 metadata
     继续由 stabilizer 处理，稳定确认无曲目后才发布 `NoTrack`。
  7. 旧 generation 的迟到结果不得更新当前歌曲的显示或状态。Phase 0 不新增缓存 TTL 或
     “过期 cache”策略。
  8. 如果没有明确放弃的用户能力，行为矩阵可以没有 `Remove`；LRC 上限行为属于
     `Redefine`，应从静默截断改为明确拒绝。
- [x] 将 `#62` 中 restart failure 与 LRC cap 拆成两个独立行为记录，禁止未来 PR 混合不相关责任。

**退出条件**：矩阵每一行都有行为 owner、输入/输出、失败语义和测试入口；所有冲突都已经写成新设计的明确决策，不能以“沿用当前实现”作为答案。

**当前执行状态（2026-08-23）**：Phase 0 已完成。policy 决策、矩阵登记、逐条 Retain public contract
test、语义 grammar/parser rule 的正负 corpus、differential comparator、`BehaviorChangeRecord` 和
当前实现的 golden baseline 均已登记并执行。标为 `target` 的场景属于 Phase 1 迁移门禁，不表示目标 API
已经存在，也不阻塞 Phase 0 退出。

### Phase 1：建立 feature contracts 和 application capabilities

**目的**：先建立独立于 Qt、D-Bus、HTTP 和文件系统的目标契约，再决定现有实现如何接入。

- [x] 在 owner feature 中新建值对象：`playback.models` 放 `TrackIdentity`、`PlaybackObservation` 和 playback status，`lyrics.models` 放 canonical lyric document 类型。
- [x] 在 `lyrics` 中新建 `MatchEvidence`、`MatchConfidence`、`ResolutionDecision` 及 invariant validator。
- [x] 在 `display.models` 中新建 `DisplayState`、`DisplayFrame` 和 display diagnostics；platform operation result 仍由 Phase 4 收口。
- [x] 在 workflow 或 feature 边界旁定义命名 Protocol；Protocol 只描述稳定业务契约，不暴露 `Any`、Qt、D-Bus 或 aiohttp 类型，不建立通用 `ports/` 包。
- [x] 将 Config 内部有限 mode 收敛成 Enum/value object，保留 JSON serializer 的字符串格式。
- [x] 加 architecture tests：feature contracts 禁止第三方 import、provider 不得写 display state、唯一 publisher、D-Bus 动态值不得越过 adapter；capability success/failure invariant 继续由 Phase 4 补齐。
- [x] 加等价性门禁：grammar、parser、matcher、resolver、display 和 platform 相关变更运行 typed corpus；禁止通过修改 expected 或读取源代码绕过。

**执行对账（2026-08-26）**：上面标记为完成的 contract、Config mode、resolver/workflow 类型和第一批
architecture/corpus 门禁已经落地。Phase 1 仍保持未闭合，剩余重点是完整的 application capability
契约、platform operation-result invariant 和 display/platform 的独立 corpus 入口；它们由 Phase 4-6
继续完成。

**退出条件**：新类型可以被测试和文档引用；各 owner feature 与 `app` capability 有独立测试；`ty` 在新边界上没有错误；没有通过 suppression 解决类型错误。

### Phase 2：统一歌词接入与展示协议（#14）

**目的**：完成 #14 的准确歌词入口，同时建立播放器适配器、歌词来源和展示层之间的稳定边界。
本阶段不是把 `MprisProvider` 和 `LyricsResolver` 搬到两个新目录，而是先把两条输入链路收敛到同一份
规范化歌词文档和展示投影。

**实现形状**：有状态、持有资源、拥有任务或协调 workflow 的责任必须由对象承载，并通过构造函数注入
协作者。具体 adapter 不继承 `Protocol`，使用 structural typing；纯值对象、纯时间轴计算、边界校验和
序列化可以保持函数或不可变 `dataclass`，因为它们没有独立生命周期或资源 owner。

**当前进度（2026-08-27）**：canonical playback/lyrics/display model、Python v1 wire decoder、MPRIS
normalized observation、generation-owned resolution decision、统一 presentation projector 和 Qt
compatibility publisher 已落地。Cider 已改为直接适配公开 HTTP API：播放状态约每 1 秒校准一次，切歌时
只拉取一次完整歌词时间轴，帧间位置由本地 `MediaClock` 推进；token 是可选依赖，空值不发送
`apptoken`。`source.provider` 在 Cider 边界归一化为稳定 `source_id`，并保留原始名称作为
`source_name`。`PlaybackCoordinator` 独立拥有 MPRIS session、订阅、poll task 和 track stabilization；
`MprisLyricsCoordinator` 独立拥有歌词 generation/task，`MprisTimeline` 独立拥有累计位置校准；
`LyricsResolver` 只通过 typed source contract 工作，`LiveLyricsSource` 与 network/local source 使用同一协议，
`DisplayCoordinator` 是唯一 Qt publisher，Overlay 只消费 `DisplayFrame`。MPRIS 外部/local/network
结果现在保留同一个 canonical `LyricsDocument`，不会把 `MPRIS:<provider>` 伪装成最终歌词来源；注入
自定义 resolver 时必须显式提供与 live source 共享的 `SourceOwnershipCoordinator`。
`LyricsSourceResult` 额外携带 `LyricsSourceKind`，由 workflow 传递 live/network/local 角色；MPRIS
不再通过具体 source id 判断 ownership。resolver 的共享 in-flight 请求由显式 `cancel_inflight()` 路径清理。

- `PlaybackCoordinator`：拥有 MPRIS session、订阅、poll task、player selection 和 track stabilization，并向 provider 输出 normalized playback observation。
- `CiderApiPort` / `CiderApiClient` / `CiderPlaybackResponseAdapter`：provider 只依赖窄的 async capability；具体 HTTP
  session、可选 token、响应 envelope 和播放事实由 client adapter 持有。
- `CiderLyricsResponseAdapter`：把 Cider 歌词/翻译响应转换成最终 provider 明确的 canonical `LyricsDocument`。
- `CiderApiProvider`：拥有 Cider HTTP 轮询、按 track generation 的单次歌词任务、取消和统一展示发布。
- `AdapterReceiver` / `AdapterProtocolDecoder`：拥有 generic `kotonoha.adapter` v1 的 snapshot/clock wire boundary；不接受旧 Cider WS 字段。
- `DisplayCoordinator` / `LyricsPresentationAdapter`：统一把 normalized playback/document 投影为 `DisplayFrame`，不直接暴露 Qt publisher 给 adapter。
- `LyricsResolutionWorkflow`：拥有 source plan、generation、in-flight tasks、取消和 resolution decision。
- `LyricsPresentationAdapter`：拥有 document/clock 到 `DisplayFrame` 的展示投影；Qt 只消费 frame。
- `QtDisplayPublisher`：唯一 publisher，把 `DisplayFrame` 写入当前 `LyricsState`，Overlay 直接消费 frame。

#### 2A. Canonical contracts

- [x] 由 `MprisPlaybackAdapter` 和未来 adapter 共同使用 `playback.models` 的 `TrackIdentity`、
  `PlaybackObservation` 和强类型 playback status。
  保留播放器原始 title、track id、URL、player identity 等 hint 证据，normalized lookup view 不能覆盖 raw view。
- [x] 在 `lyrics.models` 中定义 `LyricDocument`、`LyricLine`、`LyricWord` 和来源/匹配证据；解析器和
  provider 只输出 document，不输出当前行或 Qt state。
- [x] 在 `display.models` 中定义 `DisplayState`、`DisplayFrame` 和 diagnostics。current/previous/next、
  interlude、word progress 都是 Kotonoha 的投影结果，不属于外部播放器协议。
- [x] 删除 root `model.py` 和 legacy `LyricsSnapshot` 输入；adapter v1 只接受 normalized playback/document。

#### 2B. Versioned external adapter protocol

- [x] 由 `AdapterProtocolDecoder` 持有版本化、来源中立的 adapter message decoder；generic WS 入口至少区分
  `snapshot`、`clock`，并以显式 message kind 表示字段语义。
- [x] `CiderApiClient` 在 HTTP boundary 校验 response envelope、错误码、响应大小和可选 `apptoken`，并把
  `/playback`、`/lyrics/current`、`/lyrics/:id` 解析成 canonical facts/document。
- [x] `LyricsPresentationAdapter` 让 MPRIS、Cider HTTP 和未来播放器 adapter 都只进入 normalized
  `PlaybackObservation` / `LyricDocument`；adapter 不得直接写 `LyricsState`。
- [x] legacy Cider WS、`currentLine` 等旧字段和旧 receiver 路由已删除；外部播放器统一使用 generic adapter v1。
- [x] receiver 在 wire boundary 验证 protocol/version、finite number、track reference、timed line invariant
  和 payload budget；坏 frame 只能成为明确的 rejected/miss。

#### 2C. #14 source adapters

- [x] MPRIS adapter 一次保存 raw metadata 和 `LyricsHint`，支持播放器精确 provider id、`file://` 路径、
  sidecar 和 embedded lyrics；exact hint 失败或 provider 未启用时回退配置的 source plan。
- [x] Cider HTTP 和 MPRIS canonical path 都输出同一个 `LyricsDocument` / `DisplayFrame` contract；Cider
  response 的最终 provider 身份与 Cider transport/player 身份分开。
- [x] local、exact-id 和 network provider 收敛到同一个 lyrics source contract，输出 `LyricsSourceResult`；source 不决定展示 precedence 之外的 UI 状态。
- [x] sidecar/embedded/parser 的既有预算、正负 grammar case 和 provider matching corpus 继续作为迁移门禁。
- [x] `ordered_first` / `best_confidence` 作为显式 resolution policy 保留；默认路径使用
  `best_confidence`，Settings 显示并持久化 `prefer_best_lyrics` 开关，来源顺序仍可调整。

#### 2D. One resolution and display path

- [x] `LyricsResolutionWorkflow` 只发布带 generation 的 `ResolutionDecision`；MPRIS owner 对迟到结果执行 generation
  检查，不能更新当前 document、Cider ownership 或 display state。
- [x] `LyricsPresentationAdapter` 让新旧入口都通过同一个 `LyricsDocument -> DisplayFrame` projector；迁移期间只允许一个 compatibility
  publisher 写现有 Qt `LyricsState`。
- [x] Overlay 直接消费 `DisplayFrame`；`TimelineEngine` 已独立拥有 clock observation 和高频推进，Qt renderer
  重组与 platform lifecycle 仍留在后续 phase，避免把 #14 与 UI/platform 迁移混在一起。

#### 2E. 结构收口与生命周期 owner

- [x] `LyricsSourceResult` 只携带 canonical `LyricsDocument`；network source、live source、local/exact source
  均通过同一 `LyricsSource` contract，并显式携带 source kind；resolver 不再按 `cider` 写特殊分支或修改
  display ownership。
- [x] concrete aiohttp 只存在于 HTTP/provider adapter 边界；workflow、resolver 和 source contract 只接受
  `LyricsSession`。
- [x] `SourceOwnershipCoordinator` 替代 legacy `providers/gate.py`，统一管理 external/live/standalone ownership、
  snapshot revision、clock 与 disconnect。
- [x] receiver 严格执行 per-client sequence 单调递增、snapshot-before-clock 和 trackRef 一致性；拒绝的 clock
  不消耗 sequence。
- [x] `PlaybackCoordinator`、`MprisLyricsCoordinator`、`MprisTimeline` 和 `DisplayCoordinator` 分别拥有
  MPRIS poll、歌词 generation、位置校准和 Qt publishing；架构测试锁定依赖方向及唯一 publisher。
- [x] resolver 的共享网络任务有独立取消入口；MPRIS stop 先结束 workflow，再回收 resolver in-flight 请求，避免
  shielded lookup 在 provider 停止后继续运行。

**Phase 2 收口对账（2026-08-27）**：Cider provider 现在依赖窄的 `CiderApiPort`，具体 HTTP client
只在 composition root 创建；被 disable 或切换翻译取消的歌词任务仍由 provider 持有，并在关闭 HTTP
session 前完成等待和异常检查。`main._run` 把 startup 放入同一 `try/finally`，启动部分失败也会进入
controller cleanup。展示层删除了没有独立策略的 `LyricsIngressCoordinator` 转发模块，normalized
playback/document 直接进入 `LyricsPresentationAdapter`。这些行为由 provider cancellation、startup
failure 和 display boundary tests 覆盖；Overlay/platform/Settings 的剩余边界仍属于后续 phase。

**本阶段不做**：新增无来源依据的播放器识别表、重写 Cider transport 的重连策略、cache schema/TTL 新策略、
Display/Overlay 视觉变化、platform surface lifecycle、Settings persistence、完整 DisplayEngine/word mapping
或 translation merge。每一项若改变用户可见行为，必须另写 `BehaviorChangeRecord`。

**退出条件**：MPRIS 和 Cider HTTP 都能产生同一种 normalized playback/document 输入；#14 的 exact id、sidecar、
embedded 和 fallback 场景通过同一 source contract；展示 frame 只在 Kotonoha 内生成；旧 `LyricsSnapshot` 和
Cider 专用 WS 路由均已删除；所有 generation、payload budget、parser 和 cancellation golden scenarios 通过。
当前验证：Python 全量 `773 passed, 2 skipped`，`ruff check .`、`ty check`、架构/worker 门禁、
`git diff --check` 和 `uv build` 通过。Cider 插件的 `pnpm test` / `pnpm build` 因当前环境没有 `pnpm`
未执行；这不影响 Python 包的门禁结论，但仍是提交前的环境验证缺口。

### Phase 3：重建时间轴和展示模型

**目的**：把 #38/#46/#56/#58/#59/#62/#64 的展示行为从 QWidget 和 MPRIS 协调器中收回到统一的、可测试的展示协议。

Phase 3 不以新增一个同名包装类为目标，而是完成 `PlaybackObservation -> TimelineEngine -> DisplayEngine -> DisplayFrame`
的唯一语义链路。MPRIS 的播放器特有位置校准保留在 MPRIS 边界，不进入展示规则。

#### Phase 3.0：冻结协议和责任边界

- [x] 定义 typed `DisplayInput`：包含 `PlaybackObservation`、显式 `ResolutionState`、可选 `LyricsDocument` 和 `DisplayOptions`。
- [x] 将 `LyricsPresentationAdapter` 演进为 `DisplayEngine`；不新增只转发调用的包装层。
- [x] 规定 provider 不再通过可选 `state` 拼装展示状态；状态由完整输入和 DisplayEngine 统一推导。
- [x] 将 `DisplayFrame` 的进度字段改成有语义的 value object，不使用含义不明确的裸 progress tuple。
- [x] 明确 canonical lyric line 不被 sweep 或翻译展示过程修改；展示进度通过独立字段返回。

#### Phase 3.1：收敛时间责任

- [x] `TimelineEngine` 只负责 `MediaClock`、track anchor、pause/resume 和 normalized playback position。
- [x] 从 `display.timeline` 拆出 line selection、interlude、line sweep 等纯展示规则，避免时钟状态和歌词策略共存。
- [x] 将 `MprisTimeline` 演进为明确的 `MprisPositionCalibrator`；保留现有累计位置修正行为，但不让 DisplayEngine 依赖 MPRIS 类型。
- [x] 删除 `MprisLyricsCoordinator` 自己的 current-line 判断和重复 emit 路径。
- [x] generic receiver、Cider、MPRIS 都通过同一种 typed observation 进入 TimelineEngine，不在边界丢失 playback status 语义。

#### Phase 3.2：实现 DisplayEngine

- [x] 输出 `NoTrack/Resolving/LyricsAvailable/LyricsNotFound` 四种状态；不建立 `Empty` 或 `Finished` 状态。
- [x] 统一 current/previous/next、transition、interlude、line progress 和 diagnostic 的生成规则。
- [x] word highlight 使用 document word spans 和最终 text mapping，不假设 words 之间有空格。
- [x] `DisplayFrame` 提供语义化 `LineProgress` / `WordProgress`；UI 只负责将进度映射到像素。
- [x] offset、lead time、script transform 通过注入的 typed `DisplayOptions` 进入纯展示变换；Config 持久化仍属于 Phase 5。

#### Phase 3.3：翻译、interlude 和布局策略

- [x] translation merge 变成 document transform；timestamp alignment 和 positional alignment 都是显式策略。
- [x] 保持 #58 的排序和二分查找复杂度，覆盖乱序、重复时间戳、长度不一致和容错边界。
- [x] interlude detector 输出语义时间数据；倒计时样式和字符由渲染边界决定。
- [x] font-fit policy 独立于 Qt 字体测量；测量留在 UI adapter，fit decision 留在纯展示模块。

#### Phase 3.4：Overlay 渲染迁移

- [x] Overlay 只绑定 `DisplayFrame` 并负责 Qt 控件、QPainter、QFontMetrics、动画、窗口尺寸和像素布局。
- [x] 移除 Overlay 对当前行、interlude、translation、script、lead/offset 和 temporal progress 的业务推导。
- [x] 保留 KaraokeLabel 的无空格文字到像素映射能力，但输入改为 DisplayEngine 生成的 progress。

#### Phase 3.5：质量门禁和文档收口

- [x] 建立 Qt-free display corpus：四种状态、上下文行、transition/interlude、line/word progress、translation、offset、pause/resume、diagnostic 和不可变性。
- [x] 增加 MPRIS `NoLyricsResolution -> LyricsNotFound`、重复 tick、取消和校准回归测试。
- [x] 增加架构门禁：单一 DisplayEngine、单一展示时钟、provider 不导入展示规则、Overlay 不计算歌词时间进度。
- [x] 迁移 `lyrics.select` compatibility API，并保留带删除条件的 TODO，直到所有调用者迁移完成。
- [x] 统一 `docs/SPEC.md` 中当前协议与旧 WebSocket 历史说明，避免新旧架构并列造成误导。

#### Phase 3.6：审查问题收口（2026-08-27）

- [x] `AdapterReceiver` 的 WebSocket、POST logical client 和 receiver stop 共用 client drop 路径；关闭时清理 session、ownership、display owner 和 sequence namespace，避免旧状态或旧 sequence 泄漏到下一次连接。
- [x] `DisplayCoordinator` 对 clock task 使用 done callback，并在 restart/stop 读取已完成 task 的异常；取消仍按控制流处理，意外失败会被记录而不会变成未取出的 task exception。
- [x] `LyricsResolutionWorkflow` 在启动新 generation 前取消并等待旧 generation，避免旧 resolver 请求仍在运行时与新请求并发。
- [x] Cider 和共享 lyrics payload reader 都循环读到 EOF 并执行总字节上限；cache 将 SQLite/文件系统失败归一化为 `LyricsCacheError`，不让存储实现泄漏到 resolver/UI。
- [x] tray Settings/Quit action 使用 receiver-owned bound method；剩余 Qt signal、deferred callback 和 surface callback 的全量生命周期审查留在 Phase 4/5。

**退出条件**：可以不用 Qt 运行完整 display/timeline corpus；所有 provider 通过同一 typed display input；Overlay 只渲染 frame；
MPRIS 校准不泄漏到 display policy；lyrics provider 与 display policy 不互相导入；Python 全量测试、Ruff、ty、构建和 diff 门禁通过。

**Phase 3 收口验证（2026-08-27）**：Python 全量 `773 passed, 2 skipped`；定向 receiver/display/workflow/cache/
resolver/Cider/tray 测试 `73 passed`；`ruff check .`、`ty check`、`git diff --check` 和 `uv build` 通过。
`pnpm test` / `pnpm build` 仍受当前环境缺少 `pnpm` 影响，未执行。

### Phase 4：重建 Overlay surface/platform 生命周期（已完成）

**目的**：把 #27-#31/#35/#38/#46/#55/#60/#64 的平台行为变成可验证状态机。

- [x] 将 `platform.OverlayPlatform` 收缩为 capability-specific contracts：surface、output binding、input、blur、drag；不适用能力不要求实现无关方法。
- [x] 实现 `SurfaceLifecycleOwner`：`Unprepared -> Prepared -> Active -> Rebinding/Degraded -> Closing -> Closed`。
- [x] surface owner 负责 blur/input release、native handle 生命周期和 deferred callback guard。
- [x] output source 只提供 toolkit-neutral `Output` value object；active output 更新只有一个 command path。
- [x] rebind 失败保留 pending intent；成功后才提交 active output/config。
- [x] drag strategy 只计算 compositor-specific movement；application 根据 `Applied/Rejected` 决定保存。
- [x] Layer Shell、Qt fallback、niri、X11 capability reason 分别测试；保留真实 Wayland/KWin-compatible live lifecycle test opt-in，niri 仍需真实环境验证。
- [x] `ui/settings/` 和 `ui/overlay/` 通过同一个 `DefaultOverlayPlatformFactory` 获得 session-selected capability adapter，不自行 probe。
- [x] surface/output/drag state machine 维护 operation-result corpus；失败、pending intent、关闭后 callback 都有正向和负向场景。
- [x] 按责任拆分当前约 796 行的 Overlay 实现：`ui/overlay/window.py` 保留窗口边界，surface binding、frame-to-widget binding、presentation/paint 和 drag/geometry 分别迁到独立 owner；拆分以依赖和生命周期为边界，window 文件约 532 行，其余新模块均保持在 500 行以内。

**退出条件**：平台 fake 能完整跑 surface/drag/output 状态机；Overlay 不导入 native bridge；失败 operation 不会被伪装为成功；分散的 output lifecycle 代码收敛到唯一 owner。

**Phase 4 收口验证（2026-08-27）**：定向 Overlay/platform/Settings/architecture 测试 `169 passed`；全量 Python 测试
`778 passed, 2 skipped`；`ruff check .`、`ty check`、`git diff --check` 和 `uv build` 通过。live compositor 测试保留为显式 opt-in，当前环境未执行。

**Phase 3/4 收口后的运行审查修复（2026-08-27）**：

- [x] `TimelineEngine.observe()` 返回 `MediaClock` 的平滑 observation，而不是被拒绝的滞后轮询值；切行边界不会因一次旧位置样本回跳到上一行。
- [x] MPRIS 在 transitioning sample 和稳定 commit 两个同步入口声明 external ownership；resolver 尚未运行时，Cider/API 或 generic adapter 不能插入一帧覆盖当前播放链路。
- [x] Overlay 对同一 `LyricLine` 的重复绑定保持幂等，不重建布局或重启动画；context label 也不重复触发 `setText()`。
- [x] 增加时间轴回跳、MPRIS ownership 窗口和重复行绑定回归测试；当前全量 Python 验证为 `782 passed, 2 skipped`，其余门禁保持通过。

审查结论：MPRIS 工作流内的 provider 竞争窗口已经关闭；没有 MPRIS 时，`SourceOwnershipCoordinator` 的
`standalone` 模式仍允许多个 live adapter 直接发布，这是尚未定义仲裁策略的真实边界风险，不能把它误报为已解决。

### Phase 5：配置、Settings 与组合根收口

**目的**：让配置和 UI 不再成为跨层状态的第二套 workflow。

- [x] `ConfigStore` 负责 JSON decode/validation/atomic persistence；application 只处理 typed `Config`。应用范围内唯一的 `ConfigService` 负责变更、校验和持久化调度，不引入 `ConfigPatch` 或公开快照对象。
- [x] `SettingsFormState` 负责控件值；字段 constraints 与 Config 共用 value object，不使用 `getattr(defaults, field)`。
- [x] 所有 settings action 变成 typed intents：`ApplyConfig`、`ClearCache`、`RequestRestart`、`ChangeTrackOffset`。
- [x] `app/application_controller.py` 只负责组合、启动/停止和 intent routing；配置应用、显示源仲裁与 provider 参数转发由显式 application service/owner 处理。
- [x] 所有 async actions 由 `app/lifecycle.py` 的 supervisor 保持 task handle，并在 stop 时等待；被拒绝的 coroutine 也会显式关闭。
- [x] 完成剩余 Qt signal/deferred callback 的 owner 审计；tray Settings/Quit 已在 Phase 3 收口，Settings/Overlay callback 使用 bound method 或明确 QObject owner。
- [x] 将 Settings 按 dialog lifecycle、`SettingsFormState`、page builder 和显式 `SettingsWidgets` owner 拆分；移除 page builder 对 dialog 私有控件注册表的隐式写入。`ui/settings/dialog.py` 仍略高于 500 行，因为 Qt surface lifecycle 与 painting 必须由同一窗口 owner 管理，机械拆分会增加转发层。
- [x] Settings 可复用控件的信号只由对应 builder 在初始化时连接一次；Reset 只重建页面和刷新值，不重复注册 action signal。
- [x] 将 `ConfigStore.save()` 的同步文件写入移出 Qt signal/UI callback 的直接执行路径，交给 application-owned `ConfigService` persistence worker；连续变更合并为最新值，`close()` 等待最后一次写入。
- [x] `AppController` 只接收显式的必需 `ConfigService`；Apply 通过 service 合并表单实际变更字段，保留 Settings 打开期间的最新运行时位置、穿透和 track offset。
- [x] Settings presentation 的实际实现统一迁入 `ui/settings/`，包括 dialog、page builders、sources、widgets、theme、controls 和 form state；根目录不再保留同名实现。
- [x] 明确无 MPRIS 时多个 live adapter 的 standalone 仲裁策略：display source 由设置控制启用和顺序；仲裁按启用源优先级选择，同一源内按最新 observation 选择，并只保留一个 active owner。

**Phase 5 当前实现对账（2026-08-28）**：

- `app/composition.py` 在组合根创建并注入唯一 `ConfigService`；`ConfigStore` 负责包括 Cider token 在内的 JSON 与原子文件边界，运行时 token 与其他设置一起持久化。
- `SettingsFormState`、`SettingsWidgets`、page builders 和 typed intents 已分开；Settings 的显示源列表支持多个启用项，列表顺序会持久化并作为 standalone 仲裁优先级。
- `SourceOwnershipCoordinator` 统一维护 live candidate、source priority 和 active owner；MPRIS、Cider API、generic adapter 都通过该 owner 进入显示链路。
- `app/source_contracts.py` 提供 feature-specific source Protocol；Provider 只依赖自己需要的 source/display 能力，不再引用具体 coordinator。
- `app/source_registry.py` 只登记 candidate、candidate revision 和 clock；`app/source_matching.py` 只负责纯匹配判断，ownership arbitration 留在 `source_gate.py`。
- `config/schema.py` 是 Settings 页面分组与 `SETTINGS_CONFIG_FIELDS` 的唯一声明点；`Config.settings_values()`、Settings form 和 ConfigService 使用同一份顺序。
- `ConfigService.config` 返回 detached 配置值；所有运行时变更使用替换语义，`persistence_status` 暴露 `idle/pending/failed` 和安全错误信息，失败可通过显式 retry 重试。
- Settings builder 的 page rebuild 已与信号注册解耦：`SettingsPageBuilder` 和 `SettingsSourcesPageBuilder` 各自持有一次性连接，Reset 后 Clear Cache、source guard 和页面联动不会重复触发。
- `ConfigService.apply_settings()` 接收完整表单值和 changed-field set，只覆盖实际改过的 Settings 字段；`AppController` 不再接受第二个 `Config` 或为配置依赖创建 fallback。
- `src/kotonoha/ui/settings/` 是 Settings presentation 的当前 owner；其主题继续使用包级共享 assets，目录迁移不会改变资源路径。
- `src/kotonoha/ui/overlay/state.py` 和 `publisher.py` 是 Overlay 的 Qt frame boundary；`display/` 不再持有 Qt state 或 publisher。
- 本阶段没有引入 immutable snapshot 或 `ConfigPatch`：配置修改后立即排队落盘，关闭时等待 worker 完成；这是为保持当前设置语义而作的明确选择。
- `QProcessRestartLauncher` 是可注入的进程边界，重启失败时当前进程保持运行；测试通过真实 `AppController` 构造验证该失败路径。

**Phase 5 门禁验证（2026-08-28）**：offscreen Python 测试（排除需要绑定 socket 的 receiver）为 `792 passed, 2 skipped`；在允许绑定临时 localhost 端口的环境中，receiver 为 `16 passed`，合计 `808 passed, 2 skipped`。`ruff check .`、`ty check`、`git diff --check` 和 `uv build` 均通过。受限沙箱中的 receiver socket 失败不作为代码失败结论。

**Phase 6 执行前记录（历史缺口，当前由下方 6.1-6.7 覆盖）**：

以下条目记录进入 Phase 6 时识别的缺口，不是新的后续阶段清单。最终状态以本计划的 Phase 6 验收项和最后的验证记录为准。

- 删除 `controller.py`、`lyrics/ownership.py` 等 compatibility exports，以及 `AppController` 的可选依赖 fallback；条件是所有内部和外部调用方都改为目标模块与显式组合根注入。
- 将 Config、store、local reader 和重复 track identity key 迁移到目标 feature package，并保持 regular-file/FIFO/大小上限、原子替换和 offset identity 行为不变。
- 将 `lyrics/live_source.py` 从 `lyrics/ownership.py` 的 `LiveSourceMatch` compatibility import 迁到正式 contract；所有调用方迁移后删除兼容导出。
- 删除 `lyrics/match.py` 对 `lyrics/titles.py` 私有 helper 的依赖，按真实依赖拆分 titles/match；迁移完成前不得复制 grammar/matching helper 形成第二套规则。
- 把 `display/coordinator.py` 的 Qt publisher compatibility bridge 移到明确的 application/UI boundary，让 timeline/policy package 完全脱离 Qt。
- 统一组合根定义：当前主要 concrete object graph 仍在 `AppController`，而 `main.py` 创建 `ConfigService`，与“`app/services.py` 是唯一组装点”的计划表述不一致；Phase 6 明确最终 owner、文档和实现，只按依赖边界搬运，不为目录形式机械移动代码。
- 完成 Python 3.11-3.15 CI、Cider `pnpm test/build`、live compositor opt-in 和真实 Cider/MPRIS 联调验证，并继续收紧结构门禁。

**进入 Phase 6 时的退出条件**：Settings 的状态与 signal owner 唯一，`ConfigService` 是配置变更和持久化的唯一 application owner，`main.py`/`AppController` 的当前组合边界已被明确记录；Settings/Overlay/MPRIS 的单元测试可以使用窄 Protocol fake，不需要 `object.__new__` 填私有字段。

### Phase 5 审查收口（2026-08-28）

以下事项属于当前 Phase 5 的实现收口，完成后才进入 Phase 6；它们不改变用户可见的配置、歌词优先级或播放器行为：

- [x] 将顶层 `overlay/` 和 `karaoke_label.py` 迁移到 `ui/overlay/`，保持 Overlay 的 Qt 行为和 `platform/` contract 依赖不变；`ui/overlay/state.py` 与 `ui/overlay/publisher.py` 的边界收口已在 Phase 6 完成。
- [x] 为 Provider 与 source ownership/display 建立窄的、feature-specific Protocol；Provider 不再依赖 `SourceOwnershipCoordinator` 或 `DisplayCoordinator` 具体类。
- [x] 将 `SourceOwnershipCoordinator` 的候选登记、匹配判断和 ownership arbitration 拆成清晰职责，保持现有优先级和 active owner 语义。
- [x] 收紧 `ConfigService` 的 Config ownership：不引入 snapshot/`ConfigPatch`，但变更统一使用替换语义，读取不得暴露可绕过持久化的内部 mutable model；减少 Settings 字段 contract 漂移。
- [x] 为 Config persistence failure 提供可观察结果或状态，并覆盖写入失败、关闭等待和连续变更合并路径。
- [x] 将架构门禁从仅检查 `>800` 行扩展为默认 `<=500` 行、明确 allowlist，并把 matcher 源码字符串检查改为 AST 结构检查。
- [x] 同步本阶段实际模块路径、文件规模、CI 覆盖和验证数量，确保计划不把已存在的 CI 工作误标为未实现。

**Phase 5 审查收口退出条件**：上述项已通过行为测试、架构测试、Ruff、ty、构建和完整 Python 测试；原计划明确属于 Phase 6 的事项仍未在本收口中提前实现。

### Phase 6：最终架构收口与质量验收

**目标**：这是最后一个 Phase。Phase 6 不再产生“留待下一阶段”的迁移项；所有兼容入口、重复 owner、跨层
bridge 和未定义的组合根都必须在本阶段完成处理。已有用户行为、Settings 窗口行为和歌词匹配结果默认保持不变，
有意变化必须登记 `BehaviorChangeRecord` 并补充公共契约测试。

| 工作流 | 最终 owner | 输入 -> 输出 | 生命周期与失败语义 | 完成判据 |
| --- | --- | --- | --- | --- |
| 配置、文件与身份 | `config/`、`file_access.py`、`playback/identity.py` | 外部 JSON/路径/标题 -> typed config、read result、offset key | 配置 worker 由 `ConfigService` 等待并关闭；文件拒绝/超限返回显式 failure；损坏配置保留 `.corrupt` | 配置/文件/identity contract tests 与架构门禁通过 |
| Display 与 Qt | `display/`、`app/display_coordinator.py`、`ui/overlay/state.py`、`publisher.py` | normalized observation/document -> `DisplayFrame` -> Qt state signal | coordinator 持有 clock task；publisher 只在 composition 创建；stop 先停 producer 再释放 surface | display Qt-free、signal 去重、task shutdown 和 overlay tests 通过 |
| 组合与应用生命周期 | `app/composition.py`、`application_controller.py`、`lifecycle.py` | concrete adapters -> `ApplicationComponents` ports | composition 是唯一 concrete graph owner；controller 负责 start/stop，provider 可用性失败按边界降级并记录 | 重复 start/stop、启动清理、取消、异常关闭和真实 smoke 通过 |
| 歌词 grammar 与兼容层 | `lyrics/*_grammar.py`、`lyrics/match.py`、`app/source_contracts.py` | 外部标题/payload -> canonical source/document/evidence | 正则只在 grammar/parser；generation 和 source task 由 workflow/provider 持有；迟到结果丢弃 | typed corpus/differential、source contract 和旧入口删除门禁通过 |
| 质量与发布证据 | `tests/`、`.github/workflows/test.yml`、当前三份架构文档 | source tree/CI/runtime -> 可重复检查结果 | 本地使用 offscreen；live 检查只读或短时 smoke；不可用外部环境记录限制，不转成后续开发项 | 静态检查、全量测试、构建、插件检查和 live smoke 均有记录 |

#### 6.1 基线与边界冻结

- [x] 冻结配置、歌词匹配、DisplayFrame、Settings 窗口和应用 start/stop 的行为基线；测试必须通过公共接口和真实形状的 fake 验证。
- [x] 将所有 Phase 6 迁移项建立成 owner、输入、输出、生命周期、失败语义和删除条件明确的任务记录；禁止以“planned exception”作为完成状态。
- [x] 明确本阶段不重新迁移 `providers/` 到 `playback/`；`providers/` 继续拥有外部播放器适配器，`playback/` 拥有播放值类型和规则，依赖方向由门禁保证。

#### 6.2 配置、文件边界与 Track Identity

- [x] 将 Config、schema 和 store 迁入 `config/models.py`、`config/schema.py`、`config/store.py`，由 `config/__init__.py` 保留公共 `kotonoha.config` 导入入口；删除根目录临时转发实现。
- [x] 提取唯一的 typed `BoundedRegularFileReader` 文件边界组件；Config 与 local lyrics 分别保留自己的大小限制、错误映射和业务语义。
- [x] 保持普通文件检查、FIFO 拒绝、完整读取、大小上限、原子替换、损坏 JSON 处理和关闭失败可观察性不变，并为每个失败路径保留测试。
- [x] 将 Track Identity/offset key 放入唯一的播放领域 value owner；Config、Display、MPRIS 和歌词查询不再各自生成同一身份 key。

#### 6.3 Display 与 Qt 边界

- [x] 将 `DisplayCoordinator` 的异步 workflow/lifecycle 迁到 `app/`；它只依赖 typed display publisher protocol 和纯 DisplayEngine/TimelineEngine。
- [x] 将 `LyricsState` 与 Qt publisher 归入 `ui/overlay/`，由组合根注入；保持 signal 去重、frame equality 和 Overlay 显示行为不变。
- [x] 使整个 `display/` 包完全脱离 Qt、`LyricsState` 和具体 publisher；保留一个 concrete publisher 创建点和一个 task owner。
- [x] 删除 `display/presentation.py` 中仅为旧调用方保留的 `LyricsPresentationAdapter` 及其他确认无生产调用的兼容投影入口。

#### 6.4 唯一组合根与生命周期

- [x] 新增 `app/composition.py` 的 `ApplicationComposition`，作为唯一 concrete object graph 组装点；显式创建 ConfigService、cache、providers、platform adapter、publisher 和 coordinators。
- [x] `main.py` 只负责 CLI、Qt/qasync event loop 和进程级清理；`AppController` 只接收必需依赖并负责应用 start/stop 与 intent routing。
- [x] 删除 `AppController` 的 token store、restart launcher 等 concrete 默认 fallback；缺失依赖在组合根暴露，不在业务对象内隐式创建。
- [x] 验证启动失败、重复 start/stop、取消、超时和异常关闭路径；每个 task、session、server、surface 和 worker 都有明确 owner 和 await/close 路径。

#### 6.5 歌词语法、匹配与兼容层删除

- [x] 将 `lyrics/titles.py` 按 title grammar、normalization、artist/query variant 的实际依赖拆分；`lyrics/match.py` 只负责 evidence、confidence 和 ranking。
- [x] 所有正则归属于实际 grammar owner：歌词格式正则留在 parser，标题装饰正则留在 title grammar；禁止把规则复制到 matcher 或新模块。
- [x] 通过 typed behavior corpus、正向 case、最近邻负向 case 和新旧 differential comparator 验证迁移；未登记差异不得合并。
- [x] 将 `LiveSourceMatch` 迁入正式 source contract，删除 `lyrics/live_source.py` 对 `lyrics/ownership.py` 的过渡导入。
- [x] 删除 `controller.py`、`lyrics/ownership.py`、`lyrics/select.py`、`karaoke.py`、`LyricsPresentationAdapter`、`MprisTimeline`、Settings page forwarding 和其他无独立职责的兼容入口。
- [x] 所有内部测试、文档和运行代码迁移到最终 public contract；历史文档可以保留旧协议说明，但必须明确标记为 historical。

#### 6.6 文件职责与最终例外

- [x] `lyrics/titles.py` 的拆分必须按职责完成，不能以转发模块或复制 helper 规避行数门禁。
- [x] Settings package 使用目录内短模块名（`dialog.py`、`icons.py`、`pages.py`、`sources.py`、`theme.py`、`widgets.py`）；文件名不重复 `settings_` 目录前缀，职责由目录和类名表达。
- [x] `ui/settings/dialog.py` 和 `ui/overlay/window.py` 可在 800 行以内保留为各自完整的 Qt surface lifecycle owner；这不是临时迁移例外，必须在架构测试和文档中写明职责、上限及不得继续吸收的责任。
- [x] 任何超过 500 行的 Python 文件必须有同样的职责说明；超过 800 行一律拆分，除非有新的明确架构决策并由本阶段验收记录。

#### 6.7 最终质量门禁与验证

- [x] 架构测试改为禁止临时兼容文件、Qt/display 反向依赖、重复 identity 实现、重复 publisher/task owner、私有 grammar import 和 concrete fallback。
- [x] 补齐配置迁移、Display publisher 注入、组合根、生命周期、标题 grammar differential、兼容入口删除和失败路径测试。
- [x] 配置并核对 Python 3.11-3.15 CI 矩阵、offscreen Qt、Ruff、ty、`uv build`、`git diff --check`、Cider plugin test/build 和全部 Python 测试；本地按当前环境执行可用版本与完整门禁。
- [x] 在可用环境执行 live MPRIS、Cider HTTP/API 和 Wayland/compositor 验证；不可用的外部环境必须记录为环境限制，并提供可执行的 opt-in 命令和 fake/integration harness，不得把功能实现顺延到下一 Phase。
- [x] 更新 `docs/SPEC.md`、MPRIS/歌词协议文档、架构计划和开发验证说明，使它们只描述最终架构；删除 Phase 6 完成后仍会误导开发者的迁移说明。

**Phase 6 最终验证记录（2026-08-29）**：

- Python 行为测试：offscreen 套件（排除需要真实 localhost socket 的 receiver）`822 passed, 2 skipped`；
  在允许绑定 localhost 的环境中 receiver `18 passed`，合计 `840 passed, 2 skipped`。
- 静态与差异门禁：`ruff check .`、`ty check`、`git diff --check` 通过；架构测试、grammar/differential
  corpus、配置/Settings、publisher、失败回滚和取消路径均包含在上述测试套件中。
- 打包：`uv build` 成功，生成 sdist 和 CMake/native wheel。Cider 插件用现有依赖目录直接执行等价命令，
  Vitest `37 passed`，`vue-tsc` 和 Vite production build 通过；当前环境没有 `pnpm` 可执行文件，但锁文件、
  CI 命令和插件构建结果均存在，未产生实现性缺口。
- live 限制：本次环境中 `127.0.0.1:10767` 没有运行 Cider；用户总线在沙箱中不可访问，因此没有把真实 Cider/MPRIS
  联调或 compositor surface smoke 误记为通过。对应的 HTTP、D-Bus、Wayland 边界已有 fake/integration harness，
  可执行 live 命令仍记录在 README 和 CI；这只是当前运行环境证据限制，不是顺延到新 Phase 的开发任务。
- Cider token 保持可选：空 token 不发送 `apptoken`；非空 token 与其他设置一起由 `ConfigStore` 持久化到 `config.json`，且应用日志不打印 token。
- `keyring` 依赖和独立 credential store 已移除；token 的生命周期由唯一 `ConfigService` 统一管理。
- 本阶段没有未归属的实现后续项，也不创建 Phase 7；仅保留上述 live 环境验证作为发布前可重复执行的 smoke。

**Phase 6 最终退出条件**：

1. 源码中不存在仅为迁移保留的兼容模块、alias、fallback 或 `TODO`。
2. concrete object graph、Display publisher、配置 owner、Track Identity owner 和异步生命周期 owner 均唯一。
3. `display/` 完全 Qt-free；应用、feature、UI、platform 的依赖方向由架构门禁固定。
4. 标题 grammar/matching、配置文件边界、Settings/Overlay 行为和 start/stop 生命周期均有公共契约与失败路径证据。
5. 全量静态检查、行为测试、构建、CI 和可用的真实集成验证完成；剩余环境限制已明确记录，不存在未归属的后续工作。

## PR 拆分规则

每个 PR 只能属于一个 feature owner、一个 application workflow 或一个 platform lifecycle 主题：

1. `refactor(playback)`: 只迁移 MPRIS observation、generation、clock 和 player selection。
2. `refactor(lyrics)`: 只迁移一条 lyrics source、parser、matching 或 resolver workflow，包含行为矩阵对应测试。
3. `refactor(display)`: 只迁移 timeline/display model 与 renderer 输入。
4. `refactor(config)`: 只迁移 typed config、store 和 settings intent，不切换无关 workflow。
5. `refactor(platform)`: 只迁移 surface/output/drag lifecycle；live/fake 测试必须一起变更。
6. `refactor(ui)`: 只迁移 Qt presentation 和 intent binding，不把业务决策放回 widget。
7. `refactor(app)`: 只切换 workflow wiring、task ownership、删除旧路径和清理 compatibility。
8. `refactor(lyrics-grammar)`: 只迁移 title grammar 或 parser rule；必须附带 typed corpus、近邻负例和 differential report。

禁止把“顺手修到的另一个 case”留在当前 PR；另开 issue，写明它属于哪一个行为契约和哪个 phase。

## 每个重构 PR 的验收模板

```text
行为：
原始边界：
目标 owner：
输入类型：
输出/result 类型：
取消/超时/关闭语义：
目标行为：
淘汰的当前行为：
等价语料 case id：
canonical diff：
有意变化登记：
正向/近邻负向样本：
负向测试：
集成测试：
删除的现有路径：
验证命令：
```

## 风险与回滚

- **行为漂移**：typed corpus、正向/近邻负向样本和 differential comparison 防止正则或 corner case 在迁移中丢失。
- **双重 state publisher**：每个迁移阶段只允许一个 publisher；新旧结果对比不得同时写 HUD。
- **平台回归**：先用 fake 状态机覆盖，再用 live KWin opt-in；niri 仍标记为需要真实环境验证。
- **取消/线程泄漏**：所有资源 owner 在接口中出现；集成测试检查 stop 返回后 task/resource 数量。
- **迁移过大**：每阶段可独立合并，现有 adapter 只保留到新 port 有行为覆盖为止。

## 第一批实际工作顺序

1. 完成 Phase 0 的 policy 决策、typed corpus 和 differential comparator。
2. 修复当前 `ty` 诊断，禁止测试使用 `object.__new__` 绕过构造。
3. 先落地 feature contracts 和 `app` capability，不切换唯一 publisher。
4. 从 `RawTrackObservation -> TrackIdentity -> SourcePlan` 这条最能减少后续 patch 的链开始迁移，并逐 case 对比。
5. 再迁移 `DisplayFrame`，最后迁移 surface/platform 生命周期和组合根。

在第 4 步之前不应开始拆 `mpris.py`；Overlay 已按目标 owner 迁入 package，后续拆分仍必须有独立的生命周期或职责边界，不能只为减少行数制造转发层。
