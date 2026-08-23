# Kotonoha 架构分层与重构实施计划

> **状态：计划草案，尚未开始代码迁移**
>
> 这份计划服务于仓库作者的长期重构。它先固定行为和边界，再迁移实现；不接受“发现一个 case 就在现有协调器加一个 if”作为完成方式。

## 目标

将 Kotonoha 改造成职责清晰、强类型、可验证、可持续演进的桌面歌词系统：

- domain 不依赖外部系统；
- application 明确编排和生命周期；
- infrastructure 负责第三方系统适配和边界验证；
- presentation 只负责展示和用户意图；
- platform 负责 compositor/toolkit 事实和资源生命周期；
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

## 目标代码边界

建议目标目录如下。迁移期间可以用窄的兼容入口承接现有 import；完成切换后必须删除兼容层。

```text
src/kotonoha/
  domain/
    playback.py              # RawTrackObservation, TrackIdentity, generation values
    title_grammar.py         # pure title/artist decomposition and qualifiers
    matching.py              # MatchEvidence, confidence, ranking policy
    lyrics.py                # LyricDocument, LyricLine, word/line invariants
    timeline.py              # clock observations, line selection, offsets
    display.py               # DisplayState, DisplayFrame, interlude/word progress
    source_policy.py         # SourcePlan, ResolutionPolicy, SourceResult semantics
    overlay.py               # Surface/drag/output state values and commands
    config.py                 # Config value objects and constraints

  application/
    supervisor.py             # start/stop ownership and task registry
    playback_coordinator.py  # PlayerPort -> stabilized TrackIdentity
    lyrics_workflow.py        # generation-owned source resolution
    clock_coordinator.py      # authoritative clock source and correction
    display_coordinator.py    # LyricsState publisher from domain frames
    overlay_coordinator.py    # view model + user intents + platform commands
    settings_service.py       # ConfigPatch, persistence, restart/cache intents

  ports/
    playback.py               # PlayerPort, PlayerSample
    lyrics.py                 # LyricsSource, SourceResult, LyricsRequest
    cache.py                  # LyricsCachePort
    clock.py                  # ClockPort
    surface.py                # SurfacePort, capability/result contracts
    config.py                 # ConfigStore

  infrastructure/
    mpris/                    # dbus-fast adapter and raw value validation
    cider/                    # receiver protocol adapter; TS side has same states
    lyrics_sources/           # netease/lrclib/kugou/qq/local adapters
    cache/                    # SQLite and bounded executor/file storage
    config/                   # JSON and atomic file store
    platform/                 # Qt/native/layer-shell implementations

  presentation/
    overlay_widget.py         # QWidget rendering and event translation only
    settings_dialog.py         # controls and SettingsFormState binding
    view_models.py             # Qt-friendly immutable projections

  composition/
    main.py / controller.py    # dependency wiring, application lifecycle
```

目录名不是目标本身。每个模块必须有明确的 public contract、输入输出、owner 和测试；如果某个模块
只有转发函数而没有独立责任，不应为了“分层”创建它。

## 分阶段实施

### Phase 0：行为盘点与目标决策

**目的**：把当前实现的行为与新设计的目标行为分开，先完成 policy 决策，再开始代码迁移。

- [ ] 将歌词矩阵和 Overlay 矩阵中的行为标记为 `Retain`、`Redefine` 或 `Remove`；`Retain` 必须有用户价值和明确 owner，不能因为当前存在就默认保留。
- [ ] 为每条 `Retain` 行为补一个 public contract test；测试输入使用真实形状的 fake，不读取源代码字符串。
- [ ] 建立 `BehaviorCase[TInput, TPublicOutput]` typed corpus，先收录现有 title/parser/match/provider/overlay 测试和最近 PR 回归样本。
- [ ] 为每个正则或 parser rule 建立正向 case、近邻负向 case 和 rule id；expected 只保存 canonical public result，不保存正则实现细节。
- [ ] 用当前实现生成冻结 baseline，并实现新旧实现的 differential comparator；未登记差异不得合并。
- [ ] 建立 `BehaviorChangeRecord` 流程：任何有意改变必须同时写明 case、旧行为、新目标、用户影响和新的契约测试。
- [ ] 建立 golden scenarios：
  - MPRIS queue cumulative length/position；
  - title 与 artist 在切歌时混合；
  - raw title 含 uploader/版本/频道噪声；
  - exact song id 成功/失败/禁用 provider；
  - sidecar/embedded/network precedence；
  - network timeout、HTTP 200 错 payload、body/decompression over limit；
  - caller cancellation 与 owner shutdown；
  - Cider selected/unselected、disconnect、stale generation；
  - word timing、无空格文字、interlude、finished、font fit；
  - output unplug/replug、rebind failure、closed callback、drag failure。
- [ ] 审核设计规格 §5.4 的默认 policy，并登记作者最终决策：
  1. 来源优先级与 cache 是否严格分离；
  2. `ordered_first` 与 `best_confidence` 是否都是公开 policy；默认是哪一个；
  3. `MEDIUM` confidence 的 provisional 展示、fallback 和 cache 规则；
  4. `NoTrack/Empty/Transition/Interlude/Finished` 的 UI 内容和清空时机。
- [ ] 将 `#62` 中 restart failure 与 LRC cap 拆成两个独立行为记录，禁止未来 PR 混合不相关责任。

**退出条件**：矩阵每一行都有行为 owner、输入/输出、失败语义和测试入口；所有冲突都已经写成新设计的明确决策，不能以“沿用当前实现”作为答案。

### Phase 1：建立 domain primitives 和端口

**目的**：先建立独立于 Qt、D-Bus、HTTP 和文件系统的目标契约，再决定现有实现如何接入。

- [ ] 新建 `domain` 值对象：`PlayerId`、`SourceId`、`TrackGeneration`、`Seconds`、`ProviderSongId`。
- [ ] 新建 `RawTrackObservation`、`NormalizedTrackView`、`TrackIdentity`。
- [ ] 新建 `LyricDocument`、`LyricLine`、`LyricWord` invariant validator。
- [ ] 新建 `MatchEvidence`、`MatchConfidence`、`ResolutionPolicy`、`SourceResult`、`ResolutionDecision`。
- [ ] 新建 `DisplayState`、`DisplayFrame`、`SurfaceState`、`DragState` 和 operation result。
- [ ] 新建 `ports` Protocol；Protocol 只描述稳定业务契约，不暴露 `Any`、Qt、D-Bus 或 aiohttp 类型。
- [ ] 将 Config 内部字符串 mode 收敛成 Enum/value object，保留 JSON serializer 的字符串格式。
- [ ] 加 architecture tests：domain/application 禁止第三方 import；新 boundary 禁止 `Any`；端口 success/failure invariant 必须成立。
- [ ] 加等价性门禁：grammar、parser、matcher、resolver、display 和 platform 相关变更必须运行 corpus；禁止通过修改 expected 或读取源代码绕过。

**退出条件**：新类型可以被测试和文档引用；目标 domain/ports 有独立测试；`ty` 在新 domain/ports 上没有错误；没有通过 suppression 解决类型错误。

### Phase 2：重建播放观察与歌词解析链

**目的**：先切断最频繁 case 的源头：播放器观察和歌词 workflow。

#### 2A. MPRIS infrastructure

- [ ] 将 `MprisSession` 的动态访问集中在 adapter，输出 typed `PlayerSample`。
- [ ] deadline、D-Bus exception、empty metadata、invalid Variant 在 adapter 内转为 `BoundaryResult`。
- [ ] adapter 不返回 raw player object；`PlayerSelector` 只接受 `PlayerDescriptor`。
- [ ] `PlayerSelectionPolicy` 同时服务 runtime 和 Settings rows。

#### 2B. PlaybackCoordinator

- [ ] 将 stabilizer 作为纯 domain service；将 poll/subscription/task owner 放到 application coordinator。
- [ ] 一个 committed identity 只产生一个 generation；generation 变更时由 workflow owner 取消旧 load。
- [ ] position 读取失败不得阻止 metadata commit；clock 使用独立 observation。
- [ ] provider hint 从 raw metadata 一次生成，不能在 title cleaning 后重新猜。

#### 2C. LyricsResolutionWorkflow

- [ ] 将 `resolve_hint`、`_resolve_best`、`_resolve_sequential` 改为一个显式 `SourcePlan` 执行器。
- [ ] exact hint、local sidecar、embedded、Cider、network source 的 precedence 由 plan 测试覆盖。
- [ ] 新旧 source workflow 对同一 typed request 做 canonical comparison；请求超时、失败 reason、source 顺序和 stale generation 都属于等价输出。
- [ ] network provider 统一实现 `LyricsSource.fetch(LyricsRequest)`；HTTP/body/parser/cache 细节留在 adapter。
- [ ] 将 cache hit、network hit、miss、unavailable、failure、rejected 转为 `SourceResult`。
- [ ] shared in-flight task 的 owner 放在 workflow；`cancel_inflight` 不再作为 concrete resolver 的隐藏能力。
- [ ] 只有 high-confidence artifact 写入 cache；negative cache 只记录真实 miss，不记录 unreachable/failure。

**退出条件**：歌词行为 golden scenarios 全部通过；现有 provider adapter 可以逐个接入新 port；MPRIS coordinator 不再直接调用 network provider 或写 lyric state。

### Phase 3：重建时间轴和展示模型

**目的**：把 #38/#46/#56/#58/#59/#62/#64 的展示行为从 QWidget 和 MPRIS 协调器中收回到纯规则。

- [ ] 新建 `TimelineEngine`：接收 `LyricDocument`、clock observation、per-track offset、playback status。
- [ ] 新建 `DisplayEngine`：输出 `DisplayFrame`，显式区分 Empty/Transition/Loading/ActiveLine/Interlude/Finished/Error。
- [ ] word highlight 使用 document 中的 word spans 和最终 text mapping；不假设 words 之间有空格。
- [ ] translation merge 变成 document index/transform；保持 #58 的复杂度改进并用性能测试守住。
- [ ] interlude detector、countdown、font fit 的输入输出独立测试；字体尺寸测量留在 presentation adapter，但 fit policy 不留在 MPRIS。
- [ ] `DisplayFrame` 迁移必须通过 display corpus；比较 state、上下文行、word progress、diagnostic，不比较 QWidget 私有字段。
- [ ] `MediaClock` 只提供 clock observation；source selection 和 pause/resume policy 由 `ClockCoordinator` 决定。
- [ ] Overlay widget 改为接收 `DisplayFrame`，不再从 `LyricsSnapshot` 自己推导 provider/interlude/timing policy。

**退出条件**：可以不用 Qt 运行完整 display/timeline 测试；Overlay 只渲染 frame；lyrics provider 与 display policy 不再互相导入。

### Phase 4：重建 Overlay surface/platform 生命周期

**目的**：把 #27-#31/#35/#38/#46/#55/#60/#64 的平台行为变成可验证状态机。

- [ ] 将 `OverlayPlatform` 收缩为 capability-specific ports：surface、output binding、input、blur、drag；不适用能力不要求实现无关方法。
- [ ] 实现 `SurfaceLifecycleOwner`：`Unprepared -> Prepared -> Active -> Rebinding/Degraded -> Closing -> Closed`。
- [ ] surface owner 负责 blur/input release、native handle 生命周期和 deferred callback guard。
- [ ] output source 只提供 toolkit-neutral `OutputSnapshot`；active output 更新只有一个 command path。
- [ ] rebind 失败保留 pending intent；成功后才提交 active output/config。
- [ ] drag strategy 只计算 compositor-specific movement；application 根据 `Applied/Rejected` 决定保存。
- [ ] Layer Shell、Qt fallback、niri、X11 capability reason 分别测试；至少一个真实 KWin live lifecycle test 保留 opt-in。
- [ ] `SettingsDialog` 和 `LyricsOverlay` 通过 composition root 获得同一个 session capability snapshot/adapter，不自行 probe。
- [ ] surface/output/drag state machine 维护 operation-result corpus；失败、pending intent、关闭后 callback 都必须有正向和负向场景。

**退出条件**：平台 fake 能完整跑 surface/drag/output 状态机；Overlay 不导入 native bridge；失败 operation 不会被伪装为成功；分散的 output lifecycle 代码收敛到唯一 owner。

### Phase 5：配置、Settings 与组合根收口

**目的**：让配置和 UI 不再成为跨层状态的第二套 workflow。

- [ ] `ConfigStore` 负责 JSON decode/validation/atomic persistence；application 只处理 typed Config/ConfigPatch。
- [ ] `SettingsFormState` 负责控件值；字段 constraints 与 Config 共用 value object，不使用 `getattr(defaults, field)`。
- [ ] 所有 settings action 变成 typed intents：`ApplyConfig`、`ClearCache`、`RequestRestart`、`ChangeTrackOffset`。
- [ ] `AppController` 只负责 composition/start/stop 和 intent routing；不再承载 MPRIS、Overlay、Settings 的业务决策。
- [ ] 所有 async actions 由 application supervisor 保持 task handle，并在 stop 时 cancel/await。
- [ ] Qt signal 使用 bound method 或明确 QObject owner，不用 lambda 隐藏生命周期。

**退出条件**：组合根只做 wiring；Settings/Overlay/MPRIS 的单元测试可以使用窄 Protocol fake，不需要 `object.__new__` 填私有字段。

### Phase 6：删除被替代路径、收紧质量门禁

- [ ] 删除现有 `MprisProvider` 中已经迁移到新 owner 的 resolver/clock/display/platform policy 分支。
- [ ] 删除 `match.py` 对 `titles.py` 私有 helper 的依赖，改为公开 domain result。
- [ ] 合并 config/local 的 bounded regular-file reader，删除重复边界实现。
- [ ] 删除临时 compatibility exports/fallback，并为每个删除记录对应迁移完成条件。
- [ ] 逐步增加 Ruff/ty/architecture checks：domain Any、dynamic access、dependency direction、task ownership、public annotations。
- [ ] 完整验证 Python 3.11-3.15 CI、offscreen Qt、Cider test/build、`uv build`、live compositor opt-in。
- [ ] 更新仓库规范、运行文档和开发规则，使文档描述目标架构、边界和验证命令。

**退出条件**：没有重复 state publisher、重复 task owner 或重复 platform decision path；所有门禁和 behavior contract 通过。

## PR 拆分规则

每个 PR 只能属于一个层和一个行为主题：

1. `refactor(domain)`: 只增加值对象、纯规则和测试，不切生产 wiring。
2. `refactor(ports)`: 只定义 Protocol/result，并提供兼容 adapter。
3. `refactor(lyrics)`: 只迁移一条歌词 source/workflow，包含行为矩阵对应测试。
4. `refactor(playback)`: 只迁移 MPRIS observation/generation/clock owner。
5. `refactor(display)`: 只迁移 timeline/display model 与 renderer 输入。
6. `refactor(platform)`: 只迁移 surface/output/drag lifecycle；live/fake 测试必须一起变更。
7. `refactor(composition)`: 只切换 wiring、删除旧路径和清理 compatibility。
8. `refactor(grammar)`: 只迁移正则、title grammar 或 parser rule；必须附带 typed corpus、近邻负例和 differential report。

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
3. 先落地 `domain`/`ports` 类型，不切换唯一 publisher。
4. 从 `RawTrackObservation -> TrackIdentity -> SourcePlan` 这条最能减少后续 patch 的链开始迁移，并逐 case 对比。
5. 再迁移 `DisplayFrame`，最后迁移 surface/platform 生命周期和组合根。

在第 4 步之前不应开始拆 `mpris.py` 或 `overlay.py`；没有目标 owner 的拆分只会制造更多转发层和新的隐含边界。
