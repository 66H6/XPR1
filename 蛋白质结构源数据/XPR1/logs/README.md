# 运行日志

每次check生成logs/runs/<run_id>.json及对应reports/runs/<run_id>/。
其中记录时间、命令、版本、CPU架构、seed、实际时长、退出状态和实现文件哈希。
重复执行不覆盖既有运行报告。运行日志默认不提交Git；本次验收记录固定保存在reports/acceptance。
后续正式模型运行还需记录真实GPU、CUDA、驱动、模型权重与调度作业号。
