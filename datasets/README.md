# 数据集目录

本目录不在 Git 中保存大型数据文件。克隆课程仓库后，在仓库根目录执行：

```bash
bash scripts/download_dataset.sh
```

下载成功后应出现：

```text
datasets/yfcc_course_v1/
├── DATASET_CARD.md
├── manifest.json
├── checksums.sha256
├── debug_100000/
└── formal_1000000/
```

可随时执行 `bash scripts/check_dataset.sh` 验证数据完整性。

