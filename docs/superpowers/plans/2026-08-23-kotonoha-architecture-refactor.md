# Kotonoha 架构分层与重构实施计划

> **状态：计划草案，尚未开始代码迁移**
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
| `providers/gate.py`、`receiver.py` | Cider adapter + source ownership workflow | `lyrics/cider/`、`app/source_gate.py` | WebSocket/HTTP payload 与 Cider snapshot 不越过 adapter；active source 由 app 决定 |
| `platform/qt_host.py` | Qt WindowHost presentation adapter | `ui/window_host.py` | Qt widget/native handle translation 不进入 app 或 feature contract |
| `lyrics/*.py` | Lyrics feature contracts、parsers 和 adapters | `lyrics/models.py`、`lyrics/title_grammar.py`、`lyrics/matching.py`、`lyrics/parsers/`、`lyrics/sources/` | provider 细节留在 lyrics feature，不再依赖 root `model.py` |
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
- [ ] 为每条 `Retain` 行为补一个 public contract test；测试输入使用真实形状的 fake，不读取源代码字符串。
- [x] 建立 `BehaviorCase[TInput, TPublicOutput]` typed corpus，先收录 title、LRC/YRC/KRC parser、match、display、gate、clock 和 platform 的代表性回归样本。当前入口为 `tests/behavior_corpus.py` 与 `tests/behavior_runtime_corpus.py`，provider/source workflow 的 target corpus 在迁移对应 owner 时继续扩充。
- [ ] 为每个正则或 parser rule 建立正向 case、近邻负向 case 和 rule id；expected 只保存 canonical public result，不保存正则实现细节。
- [x] 用当前实现生成冻结 baseline，并实现新旧实现的 differential comparator；未登记差异不得合并。当前 comparator 和冻结结果位于 `tests/behavior_corpus.py`。
- [x] 建立 `BehaviorChangeRecord` 流程：任何有意改变必须同时写明 case、旧行为、新目标、用户影响和新的契约测试。模板和 #62 拆分记录位于 `docs/superpowers/behavior-changes/`。
- [ ] 建立并执行 golden scenarios（场景目录已建立，完整跨 owner 执行仍待 Phase 1）：
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

**当前执行状态（2026-08-23）**：policy 决策、矩阵登记、初始 typed corpus、differential comparator 和
`BehaviorChangeRecord` 已完成；逐条 public contract test、全部 grammar/parser rule 的正负 corpus 以及
完整 golden suite 仍是 Phase 0 的未完成工程项。

### Phase 1：建立 feature contracts 和 application capabilities

**目的**：先建立独立于 Qt、D-Bus、HTTP 和文件系统的目标契约，再决定现有实现如何接入。

- [ ] 在 owner feature 中新建值对象：`playback.models` 放 `PlayerId`、`TrackGeneration`、`RawTrackObservation`、`TrackIdentity`，`lyrics.models` 放 `SourceId`、`ProviderSongId` 和歌词文档类型。
- [ ] 在 `lyrics` 中新建 `MatchEvidence`、`MatchConfidence`、`ResolutionPolicy`、`SourceResult`、`ResolutionDecision` 及 invariant validator。
- [ ] 在 `display.models` 中新建 `DisplayState`、`DisplayFrame` 和 display diagnostics；在 `platform.overlay_contracts` 中新建 `SurfaceState`、`DragState` 和 operation result。
- [ ] 在 workflow 或 feature 边界旁定义命名 Protocol；Protocol 只描述稳定业务契约，不暴露 `Any`、Qt、D-Bus 或 aiohttp 类型，不建立通用 `ports/` 包。
- [ ] 将 Config 内部字符串 mode 收敛成 Enum/value object，保留 JSON serializer 的字符串格式。
- [ ] 加 architecture tests：feature contracts 禁止第三方 import，`app` workflow 禁止具体 adapter/UI，`ui` 禁止 native bridge；capability success/failure invariant 必须成立。
- [ ] 加等价性门禁：grammar、parser、matcher、resolver、display 和 platform 相关变更必须运行 corpus；禁止通过修改 expected 或读取源代码绕过。

**退出条件**：新类型可以被测试和文档引用；各 owner feature 与 `app` capability 有独立测试；`ty` 在新边界上没有错误；没有通过 suppression 解决类型错误。

### Phase 2：重建播放观察与歌词解析链

**目的**：先切断最频繁 case 的源头：播放器观察和歌词 workflow。

#### 2A. MPRIS playback adapter

- [ ] 将 `playback/mpris_session.py` 的动态访问集中在 adapter，输出 `playback.models.PlayerSample`。
- [ ] deadline、D-Bus exception、empty metadata、invalid Variant 在 adapter 内转为 `BoundaryResult`。
- [ ] adapter 不返回 raw player object；`PlayerSelector` 只接受 `PlayerDescriptor`。
- [ ] `PlayerSelectionPolicy` 同时服务 runtime 和 Settings rows。

#### 2B. PlaybackCoordinator

- [ ] 将 stabilizer 作为 `playback` feature 的纯规则；将 poll/subscription/task owner 放到 `app/playback_coordinator.py`。
- [ ] 一个 committed identity 只产生一个 generation；generation 变更时由 workflow owner 取消旧 load。
- [ ] position 读取失败不得阻止 metadata commit；clock 使用独立 observation。
- [ ] provider hint 从 raw metadata 一次生成，不能在 title cleaning 后重新猜。

#### 2C. LyricsResolutionWorkflow

- [ ] 将 `resolve_hint`、`_resolve_best`、`_resolve_sequential` 收进 `app/lyrics_workflow.py` 的显式 `SourcePlan` 执行器。
- [ ] 用户确认歌词、local sidecar、embedded、exact hint、Cider、network source 的 precedence 由 plan 测试覆盖。
- [ ] 新旧 source workflow 对同一 typed request 做 canonical comparison；请求超时、失败 reason、source 顺序和 stale generation 都属于等价输出。
- [ ] `lyrics/sources/` 的 network provider 统一实现命名的 source capability；HTTP/body/parser/cache 细节留在 lyrics adapter。
- [ ] 将 cache hit、network hit、miss、unavailable、failure、rejected 转为 `SourceResult`。
- [ ] shared in-flight task 的 owner 放在 `app/lyrics_workflow.py`；`cancel_inflight` 不再作为 concrete resolver 的隐藏能力。
- [ ] 只有 high-confidence artifact 写入 cache；negative cache 只记录真实 miss，不记录 unreachable/failure。

**退出条件**：歌词行为 golden scenarios 全部通过；现有 provider adapter 可以逐个接入 source capability；MPRIS coordinator 不再直接调用 network provider 或写 lyric state。

### Phase 3：重建时间轴和展示模型

**目的**：把 #38/#46/#56/#58/#59/#62/#64 的展示行为从 QWidget 和 MPRIS 协调器中收回到纯规则。

- [ ] 新建 `TimelineEngine`：接收 `LyricDocument`、clock observation、per-track offset、playback status。
- [ ] 新建 `DisplayEngine`：输出 `DisplayFrame`，显式区分 `NoTrack/Resolving/LyricsAvailable/LyricsNotFound`；
  当前行、transition 和 interlude 作为 frame 内容或时间轴结果，不建立 `Empty` 或 `Finished` 状态。
- [ ] word highlight 使用 document 中的 word spans 和最终 text mapping；不假设 words 之间有空格。
- [ ] translation merge 变成 document index/transform；保持 #58 的复杂度改进并用性能测试守住。
- [ ] interlude detector、countdown、font fit 的输入输出独立测试；字体尺寸测量留在 `ui` adapter，但 fit policy 不留在 MPRIS。
- [ ] `DisplayFrame` 迁移必须通过 display corpus；比较 state、上下文行、word progress、diagnostic，不比较 QWidget 私有字段。
- [ ] `MediaClock` 只提供 clock observation；source selection 和 pause/resume policy 由 `ClockCoordinator` 决定。
- [ ] `ui/overlay/` 改为接收 `DisplayFrame`，不再从 `LyricsSnapshot` 自己推导 provider/interlude/timing policy。

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

- [ ] 删除现有 `MprisProvider` 中已经迁移到新 owner 的 resolver/clock/display/platform policy 分支。
- [ ] 删除 `lyrics/matching.py` 对 `lyrics/title_grammar.py` 私有 helper 的依赖，改为公开 feature result。
- [ ] 合并 `config/store.py` 与 `lyrics/sources/local.py` 重复的 bounded regular-file reader，删除重复边界实现。
- [ ] 删除临时 compatibility exports/fallback，并为每个删除记录对应迁移完成条件。
- [ ] 逐步增加 Ruff/ty/architecture checks：feature contract Any、dynamic access、dependency direction、task ownership、public annotations。
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
