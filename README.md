# Claws Web

基于 `claws-info.json` 的简易 Web 数据展示系统（前后端不分离）。

## 启动

```bash
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
py -3.12 app.py
```

打开：

- http://localhost:5000/

## 页面

- 列表页：支持筛选
  - 是否开源
  - 是否支持本地部署
  - 是否支持多模态大模型
  - 是否支持Windows原生部署
- 详情页：展示单个 claw 的全部信息
