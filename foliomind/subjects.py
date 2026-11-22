"""Student course classification from evidence in sampled document text."""

import re
from uuid import uuid4

from .analysis import Analysis, Proposal
from .discovery import MAX_DOCUMENTS, representative_evidence, sample_coverage, samples
from .library import CatalogError


def cue_pattern(aliases):
    alternatives = []
    for alias in aliases:
        literal = re.escape(alias)
        if alias[0].isascii() and alias[0].isalnum():
            literal = r"(?<![a-z0-9])" + literal
        if alias[-1].isascii() and alias[-1].isalnum():
            literal += r"(?![a-z0-9])"
        alternatives.append(literal)
    return re.compile("|".join(alternatives), re.IGNORECASE)


# Aliases on the same line describe one concept, which contributes at most once per document.
# Keep additional course profiles here so the reviewer and library can use the same stable names.
COURSES = (
    ("计算机网络",
     (("计算机网络", "计网实验"),),
     (
         ("TCP", "UDP", "ICMP", "ARP", "IPv4", "IPv6", "SYN", "FIN", "握手", "序列号"),
         ("拥塞控制", "慢启动", "拥塞窗口", "重传", "往返时延", "RTT", "在途数据"),
         ("VLAN", "trunk", "交换机", "广播域"),
         ("路由表", "最长前缀", "子网", "掩码", "TTL", "traceroute", "下一跳"),
         ("NAT", "端口映射", "公网地址", "端口转发", "转换表"),
         ("DNS", "域名", "名称解析", "递归服务器"),
         ("接收窗口", "累积确认", "字节流", "流量控制"),
     ),
     ("报文", "抓包", "网关", "探测包", "丢包", "源端口", "ACK", "广播", "路由"),
    ),
    ("数据库",
     (("数据库系统", "数据库原理", "数据库实验", "关系数据库"),),
     (
         ("MVCC", "隔离级别", "可重复读", "读已提交", "一致性读", "加锁读"),
         ("联合索引", "组合索引", "复合索引", "回表", "前导列", "最左前缀", "叶节点"),
         ("行锁", "死锁", "加锁顺序", "锁等待"),
         ("执行计划", "优化器", "扫描行数", "连接顺序", "扫描记录"),
         ("写前日志", "重做日志", "撤销日志", "检查点", "日志重放", "崩溃恢复"),
         ("函数依赖", "候选键", "无损连接", "关系模式", "第三范式", "BCNF"),
         ("SQL", "WHERE", "左连接", "内连接", "子查询", "聚合查询", "空值判断"),
         ("唯一性约束", "唯一约束", "唯一键", "约束报错"),
     ),
     ("事务", "回滚", "查询", "索引", "表行", "提交", "磁盘页"),
    ),
    ("编译原理",
     (("编译原理", "编译器设计", "词法分析", "语法分析"),),
     (
         ("token", "扫描器", "标识符", "保留字", "字面量", "切成记号"),
         ("FIRST", "FOLLOW", "预测分析表", "预测分析", "非终结符", "终结符"),
         ("规约", "移进", "LR(1)", "闭包", "项目集", "向前看"),
         ("左递归", "左结合", "右结合", "语法树", "运算符优先级", "产生式"),
         ("三地址", "临时变量", "公共子表达式", "基本块", "中间表示"),
         ("自动机", "DFA", "NFA", "接受状态", "状态转移"),
         ("符号表", "作用域", "类型检查", "语义分析", "变量遮蔽"),
         ("回填", "短路表达式", "跳转指令", "条件跳转", "真假分支"),
         ("错误恢复", "同步记号", "语法错误", "分析器", "记号流"),
     ),
     ("语言", "文法", "记号", "翻译", "编译", "输入串", "表达式", "目标地址", "操作数"),
    ),
    ("Java 后端",
     (("Java 后端", "Java Web", "Spring Boot", "Spring Framework"),),
     (
         ("Spring", "Bean", "Controller", "依赖注入", "AOP", "事务注解", "事务传播"),
         ("Redis", "缓存穿透", "缓存击穿", "缓存雪崩", "缓存重建", "缓存过期", "重建是否互斥"),
         ("线程池", "Executor", "拒绝策略", "任务队列", "线程中断"),
         ("ThreadLocal", "拦截器", "登录态", "请求上下文"),
         ("HashMap", "hashCode", "equals", "ConcurrentHashMap", "可变对象作为键"),
         ("volatile", "synchronized", "JUC", "计数器"),
         ("消息重投", "重复投递", "异步消费者", "消息确认", "回执", "MQ"),
         ("JVM", "GC", "强引用", "堆直方图", "垃圾回收"),
         ("秒杀", "幂等标识", "抢购", "库存扣减", "分布式锁"),
     ),
     ("Java", "用户请求", "业务", "工作线程", "缓存", "消费者", "线程", "订单", "代理", "可见性"),
    ),
    ("数据结构",
     (("数据结构课程", "数据结构实验", "数据结构与算法"),),
     (
         ("顺序表", "单链表", "双向链表", "链表反转"),
         ("栈顶", "入栈", "出栈", "循环队列", "双端队列"),
         ("二叉树", "前序遍历", "中序遍历", "后序遍历", "平衡树", "红黑树"),
         ("邻接矩阵", "邻接表", "最小生成树", "拓扑排序", "Dijkstra"),
         ("堆排序", "归并排序", "快速排序", "插入排序", "时间复杂度"),
         ("哈希表", "散列表", "线性探测", "链地址法"),
     ),
     ("遍历", "节点", "数组", "队列", "指针", "图论", "查找"),
    ),
    ("操作系统",
     (("操作系统实验", "操作系统原理"),),
     (
         ("进程调度", "时间片轮转", "多级反馈队列", "就绪队列"),
         ("虚拟内存", "缺页中断", "页面置换", "页表", "TLB"),
         ("信号量", "PV 操作", "进程同步", "临界区"),
         ("系统调用", "用户态", "内核态", "中断处理"),
         ("inode", "文件系统", "磁盘调度", "文件描述符"),
     ),
     ("操作系统", "内核", "进程", "内存管理", "上下文切换"),
    ),
    ("计算机组成原理",
     (("计算机组成原理", "计组实验"),),
     (
         ("运算器", "ALU", "算术逻辑单元", "补码", "溢出判断"),
         ("指令周期", "微程序", "微指令", "控制器"),
         ("指令流水线", "数据冒险", "控制冒险", "转发单元"),
         ("Cache 映射", "组相联", "主存", "存储层次"),
         ("DMA", "数据总线", "地址总线", "MAR", "MDR"),
     ),
     ("寄存器", "指令集", "时钟周期", "CPU", "数据通路", "高速缓存"),
    ),
    ("软件工程",
     (("软件工程导论", "软件工程实验"),),
     (
         ("需求规格说明", "需求分析", "功能需求", "非功能需求"),
         ("UML", "用例图", "类图", "时序图", "活动图"),
         ("敏捷开发", "Scrum", "瀑布模型", "软件生命周期"),
         ("黑盒测试", "白盒测试", "等价类划分", "边界值分析"),
         ("配置管理", "持续集成", "验收准则"),
     ),
     ("软件工程", "用例", "需求", "开发流程", "测试用例", "质量保证"),
    ),
    ("高等数学",
     (("高等数学", "微积分"),),
     (
         ("数列极限", "函数极限", "洛必达", "等价无穷小"),
         ("导数", "微分中值定理", "泰勒展开", "偏导数"),
         ("不定积分", "定积分", "反常积分", "二重积分", "换元积分"),
         ("微分方程", "可分离变量", "齐次微分方程"),
         ("幂级数", "傅里叶级数", "收敛半径"),
     ),
     ("极限", "可导", "连续性", "积分", "函数", "求导"),
    ),
    ("线性代数",
     (("线性代数",),),
     (
         ("行列式", "代数余子式", "克拉默法则"),
         ("特征值", "特征向量", "对角化", "相似矩阵"),
         ("矩阵的秩", "矩阵秩", "初等行变换", "齐次线性方程组"),
         ("线性无关", "线性相关", "向量组", "基变换", "张成空间"),
         ("二次型", "正定矩阵", "合同变换"),
     ),
     ("矩阵", "向量", "逆矩阵", "方程组", "线性变换"),
    ),
    ("概率论与数理统计",
     (("概率论", "数理统计"),),
     (
         ("条件概率", "贝叶斯公式", "全概率公式", "独立事件"),
         ("随机变量", "概率分布", "概率密度", "正态分布", "二项分布"),
         ("方差", "协方差", "相关系数"),
         ("大数定律", "中心极限定理"),
         ("假设检验", "置信区间", "最大似然估计", "样本均值"),
     ),
     ("概率", "数学期望", "总体", "估计量", "抽样", "显著性", "标准差"),
    ),
    ("大学英语",
     (("大学英语", "英语四级", "英语六级", "CET-4", "CET-6"),),
     (
         ("听力理解", "长对话", "听力原文", "听力练习"),
         ("选词填空", "段落匹配", "仔细阅读", "阅读理解"),
         ("汉译英", "英汉翻译", "英文写作", "英语作文"),
         ("定语从句", "虚拟语气", "非谓语动词", "主谓一致"),
     ),
     ("词汇", "搭配", "范文", "语法", "真题", "翻译", "写作"),
    ),
)

SUBJECT_NAMES = tuple(course[0] for course in COURSES)
COURSE_PATTERNS = tuple(
    (name, tuple(
        [(3, cue_pattern(group)) for group in titles]
        + [(2, cue_pattern(group)) for group in concepts]
        + [(1, cue_pattern(support))]
    ))
    for name, titles, concepts, support in COURSES
)


def match_courses(body):
    candidates = []
    for name, patterns in COURSE_PATTERNS:
        score, cues = 0, []
        for weight, pattern in patterns:
            hit = pattern.search(body)
            if hit is not None:
                score += weight
                cues.append(hit.group())
        if score:
            candidates.append((score, name, tuple(dict.fromkeys(cues))))
    return sorted(candidates, key=lambda item: (-item[0], item[1]))


def build_subject_proposal(records, stop):
    if len(records) > MAX_DOCUMENTS:
        raise CatalogError(f"本次课程分类最多审核 {MAX_DOCUMENTS} 份资料，请选择较小的目录。")
    rows = []
    for record in records:
        if stop.is_set():
            return None
        parts = samples(record) if record.available else ()
        body = "\n".join(piece for _, _, _, piece in parts)
        if not body.strip():
            rows.append(Analysis(record.id, record.digest, detail=record.detail or "没有可用于分类的正文。"))
            continue
        candidates = match_courses(body)
        course, evidence = "", ()
        detail = "正文未匹配到内置课程，请人工选择归属。"
        if candidates:
            best_score, name, cues = candidates[0]
            runner_up_score = candidates[1][0] if len(candidates) > 1 else 0
            evidence = (representative_evidence(parts, cues),)
            if best_score < 3:
                detail = f"可能属于{name}，正文线索不足，请人工确认。"
            elif best_score - runner_up_score < 2:
                detail = f"同时匹配{name}和{candidates[1][1]}，请人工确定主归属。"
            else:
                course = name
                detail = "正文匹配线索：" + "、".join(cues)
        rows.append(Analysis(record.id, record.digest, course=course, evidence=evidence,
                             review=not bool(course), detail=detail, **sample_coverage(record, parts)))
    used = {row.course for row in rows if row.course}
    pending = sum(row.review for row in rows)
    return Proposal(uuid4().hex, 1, tuple(rows),
                    f"学生课程分类 · {len(used)} 门课程，{pending} 份待确认，共 {len(rows)} 份资料。",
                    mode="subject")
