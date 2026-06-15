# 命令权限判断

命令先规范化，再依次检查 hard deny、ask、plan ask。hard deny 直接拒绝，ask 进入 HITL，低风险命令才执行。
