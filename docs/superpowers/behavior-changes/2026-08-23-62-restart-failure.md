# #62 restart failure

- `case_id`: `lifecycle.restart-replacement-failure`
- `status`: `Implemented`
- `owner`: application lifecycle/controller
- `old_behavior`: 当前实例启动替代进程失败时仍然退出，用户看到的是应用消失而不是重启失败。
- `new_contract`: 只有替代进程确认启动成功后当前实例才退出；启动失败返回可观察的失败结果并保留当前实例。
- `user_impact`: 语言切换或配置重启失败时，用户不会失去正在运行的应用。
- `reason`: 退出动作不能代表替代进程已经启动；这是把“请求已发出”误报成“操作成功”。
- `replacement_tests`: `tests/test_controller.py::test_a_restart_that_cannot_start_the_replacement_stays_up`。
- `removal_condition`: 不适用；这是当前 lifecycle contract，而不是兼容迁移行为。
