# 普通 Markdown 验收文档

> Author: Markdown Stylist
> Scenario: no source TOC

这份文档没有 `[TOC]`，用于验证侧边栏目录会独立生成。行内公式示例：$E=mc^2$。

## 中文标题

正文段落用于观察行距、宽度和段落间距。链接示例：[OpenAI](https://openai.com)。

### English Heading

重复标题需要生成稳定且不冲突的锚点。

### English Heading

第二个同名英文标题用于验证重复标题跳转。

#### H4 Section

##### H5 Section

###### H6 Section

多级标题用于验证侧边栏缩进与展开收起。

## 公式

块级公式：

$$
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
$$

矩阵：

$$
\begin{bmatrix}
1 & 2 \\
3 & 4
\end{bmatrix}
\begin{bmatrix}
x \\
y
\end{bmatrix}
=
\begin{bmatrix}
1x + 2y \\
3x + 4y
\end{bmatrix}
$$

## 代码与表格

```python
def forecast(price, load):
    return price * 0.7 + load * 0.3
```

| 指标 | 值 | 说明 |
| --- | ---: | --- |
| MAE | 12.4 | 平均绝对误差 |
| RMSE | 18.9 | 均方根误差 |

> 这是一段引用，用于验证正式报告里的提示样式。

![验证图](diagram.svg)

## 列表

- 第一层
  - 第二层
    - 第三层
- 结束
