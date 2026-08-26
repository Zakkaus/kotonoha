# Kotonoha 架构分层与重构实施计划

> **状态：持续实施中；Phase 2/#14 主链路已落地，Phase 3 的时间轴基础已开始，Phase 4/5 尚未开始**
>
> 这份计划服务于仓库作者的长期重构。它先固定行为和边界，再迁移实现；不接受“发现一个 case 就在现有协调器加一个 if”作为完成方式。

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
- 不先按文件大小机械拆分 `mpris.py`、`overlay.py`、`settings_dialog.py`。
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
- 当前 `prefer_best_lyrics` 会触发 resolver 的并发 source fetch，与确定性的 ordered source plan 存在冲突；这是必须在重构前明确的行为决策。

## 目标代码边界与目录拆分

这里参考 `bilihud/docs/architecture/module-boundaries.md` 的 feature-first 取向，但不机械复制业务名称。
目录表达的是 owner，而不是抽象层口号：一个 feature package 可以同时拥有自己的稳定值类型、纯规则、
解析器和具体外部适配；`app/` 只编排这些能力，不把它们重新包装成一个泛化的 `infrastructure/`。
因此目标结构中不建立通用的 `domain/`、`infrastructure/`、`ports/`、`presentation/`、`composition/` 或
`shared/` 包。

迁移期间可以用窄的兼容入口承接现有 import；完成切换后必须删除兼容层。目标目录如下：

```text
src/kotonoha/
  app/                         # workflow、生命周期、能力契约和 composition wiring
    application_controller.py # 创建/启动/停止应用服务，保持关闭顺序
    services.py                # 唯一的 concrete adapter object graph 组装点
    lifecycle.py               # TaskScope/Supervisor 和取消/等待语义
    playback_coordinator.py    # Player capability -> stabilized TrackIdentity/generation
    lyrics_workflow.py         # generation-owned SourcePlan 执行和结果发布
    clock_coordinator.py       # authoritative clock source 和 correction policy
    display_coordinator.py     # DisplayFrame publisher
    overlay_coordinator.py     # overlay state、user intent 和 platform command
    settings_service.py        # ConfigPatch、持久化和 restart/cache intent
    source_gate.py             # standalone/external/Cider source ownership

  playback/                    # 播放功能的 contracts、规则和 MPRIS adapter
    models.py                  # PlayerDescriptor、RawTrackObservation、TrackIdentity 等
    clock.py                   # media-clock observation 的纯规则和 adapter contract
    mpris.py                   # MPRIS polling/subscription adapter facade
    mpris_session.py           # dbus-fast session boundary
    mpris_track.py             # raw metadata validation/normalization
    player_selection.py        # player discovery 和 selection policy

  lyrics/                     # 歌词功能的 contracts、解析、匹配、source/cache adapter
    models.py                  # LyricDocument、LyricLine、LyricWord、LyricsArtifact
    title_grammar.py           # title/artist decomposition、qualifier 和 normalizer
    matching.py                # MatchEvidence、confidence 和 ranking policy
    parsers/                   # LRC/KRC/YRC parser 及 translation/word invariant
    sources/                   # Netease/LRCLib/Kugou/QQMusic/local adapter
    cache.py                   # bounded SQLite/file cache boundary
    cider/                     # Cider payload contract、receiver 和 Cider adapter

  display/                    # 纯展示模型和时间轴规则
    models.py                  # DisplayState、DisplayFrame 和 display diagnostics
    timeline.py                # line selection、offset、interlude 和 clock-independent display facts
    karaoke.py                 # line/word progress 和 font-fit policy 的纯部分

  config/                     # typed configuration 和持久化边界
    models.py                  # Config、ConfigPatch 和 constraints
    store.py                   # JSON decode/validate/atomic persistence

  platform/                   # toolkit-neutral contracts 与桌面/native adapters
    overlay_contracts.py       # capability、geometry、output、drag 和 operation result
    window_platform.py         # capability selection/registry
    qt_window.py               # generic Qt window adapter
    layer_shell.py             # Layer Shell/niri adapter
    native.py / detect.py      # native bridge loading 和 environment probe

  ui/                         # Qt presentation，按 user-facing responsibility 分组
    overlay/                   # QWidget window、KaraokeLabel 和 state binding
    settings/                  # dialog、form state 和 settings pages
    tray/                      # tray menu、icon selection 和 commands
    window_host.py             # Qt presentation binding for platform contracts
    icons.py / leaf_icon.py    # Qt resource/rendering helpers
    i18n.py / strings.py       # presentation text and language binding

  main.py                     # process entry、Qt/qasync event loop 和 last-resort cleanup
```

`app/services.py` 是组合根例外：它可以 import concrete adapters，并把同一份 config、cache、platform
capability 和 workflow wiring 组装起来；`app/` 下的 workflow 与 capability contract 不能反向依赖
Qt、aiohttp、dbus-fast、native bridge 或具体 source adapter。`main.py` 只负责进程级启动和事件循环，
不承载歌词、播放器或 Overlay 的业务决策。

| Owner | 负责 | 可以依赖 | 不得依赖 |
| --- | --- | --- | --- |
| `app/` workflow | use case、generation、source plan、intent routing、task/resource lifecycle | feature contract、platform contract、标准库 | Qt presentation、network/dbus/native concrete adapter；`services.py` 之外不得组装实现 |
| feature package contracts | `lyrics`/`playback`/`display`/`config` 的 typed values、状态、错误和纯规则 | 标准库及其他稳定 feature contract | Qt、aiohttp、dbus-fast、文件/平台 API、raw third-party object |
| feature package adapters | 网络、文件、D-Bus 和第三方数据的解析/验证/归一化 | 本 feature contract、外部库、命名 capability contract | UI 决策、跨 feature workflow state |
| `ui/` | QWidget、dialog、tray、输入翻译和 state binding | app contract、feature values、Qt | 网络/session/cache、配置持久化、具体平台实现和 native bridge |
| `platform/` | compositor/toolkit facts、capability probe、surface/output/drag/native resource | toolkit/native API、toolkit-neutral platform contract | 歌词/provider policy、UI workflow 和应用状态决策 |
| `main.py` | CLI、Qt/qasync event loop、last-resort cleanup | `app/services.py`、application controller、Qt/qasync | 具体业务 policy 和 feature 内部状态 |

### 边界规则

- feature contract 只依赖标准库和其他稳定 feature contract；第三方对象必须在 feature adapter
  边界解析、验证并归一化后才能进入 workflow。
- application workflow 只依赖命名的 capability contract；协议应放在所属 workflow 或 feature
  旁边，例如 `app/lyrics_workflow.py` 的 source capability，而不是集中到 `ports/`。
- `ui/` 可以依赖 `app` contract、feature value 和 Qt，但不能创建 network/session/cache，也不能
  自己读取 desktop name、Qt platform name 或 native bridge。
- `platform/overlay_contracts.py` 只描述 toolkit-neutral capability/result；Qt、Wayland、Layer Shell
  和 `ctypes` 只出现在 `platform` adapter 内。surface、blur、input、output、drag 的失败必须返回
  `Rejected`/`Unavailable`/`Degraded` 等实际结果及可展示 reason。
- application 是异步 task、session、server 和 surface lifecycle 的 owner；UI signal 只提交 intent，
  不创建无 owner 的 background task。
- 配置只由 `config/` 持有一套 typed model；旧的 root `config.py`、`model.py`、`state.py` 等入口只能
  在迁移期转发，并写明删除条件。
- package 内没有独立责任的转发模块不应被创建；目录拆分必须同时带 public contract、owner、输入/输出
  语义和对应测试。

### 当前实现到目标 owner 的迁移映射

| 当前实现 | 目标 owner | 目标位置 | 边界意图 |
| --- | --- | --- | --- |
| `controller.py` | 应用组合和 workflow wiring | `app/application_controller.py`、`app/services.py` 及各 coordinator | controller 不再拥有 MPRIS、歌词解析、Overlay 或 Settings policy |
| `providers/mpris*.py`、`players.py` | Playback feature adapter/contracts | `playback/` | D-Bus/raw metadata 只在 adapter 内解析；poll/subscription task 归 `app/playback_coordinator.py` |
| `providers/player_selection.py` | Playback selection policy | `playback/player_selection.py` | runtime 和 Settings 共用同一 typed descriptor/policy |
| `providers/gate.py`、`receiver.py` | Cider adapter + source ownership workflow | `lyrics/ownership.py`、`receiver.py` | legacy gate 已删除；WebSocket/HTTP payload 先归一化，active source 由 ownership coordinator 决定 |
| `platform/qt_host.py` | Qt WindowHost presentation adapter | `ui/window_host.py` | Qt widget/native handle translation 不进入 app 或 feature contract |
| `lyrics/*.py` | Lyrics feature contracts、parsers 和 adapters | `lyrics/models.py`、`lyrics/title_grammar.py`、`lyrics/matching.py`、`lyrics/parsers/`、`lyrics/sources.py`、`lyrics/network_sources.py`、`lyrics/live_source.py` | provider 细节留在 lyrics feature；source contract 不依赖 display 或 concrete HTTP client |
| `model.py` | 按语义拆分的 feature values | `lyrics/models.py`、`playback/models.py`、`display/models.py`、`lyrics/cider/` | 不保留一个跨 feature 的万能 model module |
| `clock.py`、`karaoke.py` | Playback observation / display rules | `playback/clock.py`、`display/timeline.py`、`display/karaoke.py` | 纯规则留在 owner feature，时间源选择和发布由 app coordinator 负责 |
| `overlay.py` | Overlay application workflow + Qt presentation | `app/overlay_coordinator.py`、`ui/overlay/`、`platform/` | QWidget 只渲染 `DisplayFrame`、翻译输入和显示平台结果 |
| `settings_dialog.py`、`tray.py`、`icons.py`、`leaf_icon.py` | Qt presentation | `ui/settings/`、`ui/tray/`、`ui/` | UI 通过 app capability 和 typed intent 工作，不直接保存配置或探测平台 |
| `config.py` | Config model/store | `config/models.py`、`config/store.py` | JSON decode、validation、atomic persistence 只有一个 owner |

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
  2. `ordered_first` 与 `best_confidence` 都是公开 policy，默认使用 `ordered_first`，因为
     默认行为应保持本地优先；`best_confidence` 作为可选策略。
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
- [x] `ordered_first` / `best_confidence` 作为显式 resolution policy 保留；默认路径先保证 `ordered_first`，
  不因协议迁移删除现有 `prefer_best_lyrics` 能力。

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
当前验证：Python 全量 `743 passed, 2 skipped`，`ruff check .`、`ty check`、架构/worker 门禁、
`git diff --check` 和 `uv build` 通过。Cider 插件的 `pnpm test` / `pnpm build` 因当前环境没有 `pnpm`
未执行；这不影响 Python 包的门禁结论，但仍是提交前的环境验证缺口。

### Phase 3：重建时间轴和展示模型

**目的**：把 #38/#46/#56/#58/#59/#62/#64 的展示行为从 QWidget 和 MPRIS 协调器中收回到纯规则。

- [x] 新建 `TimelineEngine`：接收 normalized playback observation/status，负责 per-track clock anchor 和高频推进；
  lyric document 投影继续由 `LyricsPresentationAdapter` 持有。
- [ ] 新建 `DisplayEngine`：输出 `DisplayFrame`，显式区分 `NoTrack/Resolving/LyricsAvailable/LyricsNotFound`；
  当前行、transition 和 interlude 作为 frame 内容或时间轴结果，不建立 `Empty` 或 `Finished` 状态。
- [ ] word highlight 使用 document 中的 word spans 和最终 text mapping；不假设 words 之间有空格。
- [ ] translation merge 变成 document index/transform；保持 #58 的复杂度改进并用性能测试守住。
- [ ] interlude detector、countdown、font fit 的输入输出独立测试；字体尺寸测量留在 `ui` adapter，但 fit policy 不留在 MPRIS。
- [ ] `DisplayFrame` 迁移必须通过 display corpus；比较 state、上下文行、word progress、diagnostic，不比较 QWidget 私有字段。
- [x] `MediaClock` 只提供 clock observation；source selection 不在 `MediaClock` 内，暂停/恢复由
  `TimelineEngine` 根据 normalized playback status 同步。
- [x] `ui/overlay/` 改为接收 `DisplayFrame`，不再从 `LyricsSnapshot` 自己推导 provider/interlude/timing policy。

**退出条件**：可以不用 Qt 运行完整 display/timeline 测试；Overlay 只渲染 frame；lyrics provider 与 display policy 不再互相导入。

### Phase 4：重建 Overlay surface/platform 生命周期

**目的**：把 #27-#31/#35/#38/#46/#55/#60/#64 的平台行为变成可验证状态机。

- [ ] 将 `platform.OverlayPlatform` 收缩为 capability-specific contracts：surface、output binding、input、blur、drag；不适用能力不要求实现无关方法。
- [ ] 实现 `SurfaceLifecycleOwner`：`Unprepared -> Prepared -> Active -> Rebinding/Degraded -> Closing -> Closed`。
- [ ] surface owner 负责 blur/input release、native handle 生命周期和 deferred callback guard。
- [ ] output source 只提供 toolkit-neutral `OutputSnapshot`；active output 更新只有一个 command path。
- [ ] rebind 失败保留 pending intent；成功后才提交 active output/config。
- [ ] drag strategy 只计算 compositor-specific movement；application 根据 `Applied/Rejected` 决定保存。
- [ ] Layer Shell、Qt fallback、niri、X11 capability reason 分别测试；至少一个真实 KWin live lifecycle test 保留 opt-in。
- [ ] `ui/settings/` 和 `ui/overlay/` 通过 `app/services.py` 获得同一个 session capability snapshot/adapter，不自行 probe。
- [ ] surface/output/drag state machine 维护 operation-result corpus；失败、pending intent、关闭后 callback 都必须有正向和负向场景。

**退出条件**：平台 fake 能完整跑 surface/drag/output 状态机；Overlay 不导入 native bridge；失败 operation 不会被伪装为成功；分散的 output lifecycle 代码收敛到唯一 owner。

### Phase 5：配置、Settings 与组合根收口

**目的**：让配置和 UI 不再成为跨层状态的第二套 workflow。

- [ ] `ConfigStore` 负责 JSON decode/validation/atomic persistence；application 只处理 typed Config/ConfigPatch。
- [ ] `SettingsFormState` 负责控件值；字段 constraints 与 Config 共用 value object，不使用 `getattr(defaults, field)`。
- [ ] 所有 settings action 变成 typed intents：`ApplyConfig`、`ClearCache`、`RequestRestart`、`ChangeTrackOffset`。
- [ ] `app/application_controller.py` 只负责 wiring/start/stop 和 intent routing；不再承载 MPRIS、Overlay、Settings 的业务决策。
- [ ] 所有 async actions 由 `app/lifecycle.py` 的 supervisor 保持 task handle，并在 stop 时 cancel/await。
- [ ] Qt signal 使用 bound method 或明确 QObject owner，不用 lambda 隐藏生命周期。

**退出条件**：`app/services.py` 和 `main.py` 只做 wiring；Settings/Overlay/MPRIS 的单元测试可以使用窄 Protocol fake，不需要 `object.__new__` 填私有字段。

### Phase 6：删除被替代路径、收紧质量门禁

- [x] 删除现有 `MprisProvider` 中已经迁移到新 owner 的 resolver/clock/display policy 分支；剩余 facade 只负责 wiring 和配置转发。
- [ ] 删除 `lyrics/matching.py` 对 `lyrics/title_grammar.py` 私有 helper 的依赖，改为公开 feature result。
- [ ] 合并 `config/store.py` 与 `lyrics/sources/local.py` 重复的 bounded regular-file reader，删除重复边界实现。
- [ ] 删除临时 compatibility exports/fallback，并为每个删除记录对应迁移完成条件。
- [x] 逐步增加 Ruff/ty/architecture checks：feature contract transport imports、provider/display direction、
  unique publisher、D-Bus dynamic values、oversized module scope、broad exception handlers 和 public annotations。
- [ ] 完整验证 Python 3.11-3.15 CI、offscreen Qt、Cider test/build、`uv build`、live compositor opt-in。
- [ ] 更新仓库规范、运行文档和开发规则，使文档描述目标架构、边界和验证命令。

**退出条件**：没有重复 state publisher、重复 task owner 或重复 platform decision path；所有门禁和 behavior contract 通过。

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

在第 4 步之前不应开始拆 `mpris.py` 或 `overlay.py`；没有目标 owner 的拆分只会制造更多转发层和新的隐含边界。
