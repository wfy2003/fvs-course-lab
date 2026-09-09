# 基于 SSD 的过滤向量检索系统课程实验

本实验使用统一的 YFCC 真实标签工作负载，对 PipeANN-Filter 和 GateANN 两种 SSD-resident 过滤向量检索设计进行复现、测试与比较。

学生只需在 10 万向量的 Debug 数据上构建索引；100 万向量的 Formal 实验直接使用课程提供的预构建索引，以减少机器资源和等待时间。数据集、预构建索引和第三方源码均不提交到本仓库。

## 开始之前

建议环境：x86-64 Linux、Ubuntu 22.04/24.04、16 GiB 内存、至少 25 GiB 可用 SSD 空间。两套系统的正式查询在资源受限 PC 上均可运行，GateANN 不要求把完整图索引载入内存。

安装公共依赖：

```bash
sudo apt update
sudo apt install -y build-essential cmake git curl zstd \
  libaio-dev libgoogle-perftools-dev libopenblas-dev libeigen3-dev
```

## 快速开始

### 1. 克隆课程仓库并下载数据

```bash
git clone https://github.com/wfy2003/fvs-course-lab.git
cd fvs-course-lab
bash scripts/download_dataset.sh
bash scripts/check_dataset.sh
```

数据集解压到 `datasets/yfcc_course_v1/`，其中 Debug 为 10 万向量，Formal 为 100 万向量。

### 2. 获取并编译两套系统

```bash
bash scripts/prepare_pipeann.sh
bash scripts/prepare_gateann.sh
```

脚本会克隆课程固定的源码提交、使用统一 AIO backend 编译，并自动为 GateANN 应用课程提供的一行兼容性补丁。默认源码目录为 `systems/`，也可把自定义目录作为脚本第一个参数传入。

### 3. 在 Debug 数据上构建并查询

```bash
python3 adapters/pipeann_adapter.py build \
  --repo "$PWD/systems/PipeANN" \
  --dataset-root "$PWD/datasets/yfcc_course_v1" \
  --tier debug --run-root "$PWD/course_runs" --threads 8

python3 adapters/gateann_adapter.py build \
  --repo "$PWD/systems/GateANN-public" \
  --dataset-root "$PWD/datasets/yfcc_course_v1" \
  --tier debug --run-root "$PWD/course_runs" --threads 8
```

索引构建成功后，一键执行两套系统的 High workload 并检查正确性：

```bash
bash scripts/run_debug_validation.sh
```

脚本每次生成新的 run-id，可安全重跑；检查器会核对两套系统的退出状态、数据规模、查询数、K、L、线程参数，并要求 High workload 的 Recall@10 不低于 80%。Debug 结果用于排错，不作为正式分析数据。

### 4. 下载正式索引并运行统一实验

```bash
bash scripts/download_indexes.sh
bash scripts/check_indexes.sh
bash scripts/run_formal_experiments.sh
```

最后一条命令默认独立重复 3 次。每次包含每套系统 5 个配置：High Selectivity 上的 3 档搜索预算，以及固定代表性预算下的 Medium、Low；两套系统合计 10 行结果。参数固定在 `config/experiments.env`，未经说明不要修改。

聚合结果位于：

```text
course_runs/experiments/<experiment-id>/results.csv
```

原始命令、日志和单次结果位于 `course_runs/results/`。详细任务、图表要求和提交规范见 [实验说明](docs/实验说明.md)，论文和系统源码见 [参考文献与源码入口](docs/参考资料.md)，环境问题见 [系统准备说明](docs/系统准备.md)，写作结构见 [实验报告模板](docs/实验报告模板.md)。

> 各脚本的输入、输出、参数和重试行为见[《脚本使用说明》](docs/脚本使用说明.md)。
