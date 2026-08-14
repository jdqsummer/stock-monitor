---
name: invest-framework-probe
description: 探针：验证 DSH 是否兼容自研 frontmatter 字段
version: 1.0.0
type: qualitative
output_field: qualitative_analysis
order: 2
depends_on: [financials, current_price]
blocks_dir: blocks
tags: [探针]
---
# 探针

这是一次 frontmatter 兼容性验证。请用一句话回答：你是否能读取本文件 frontmatter 中 type / output_field / order / depends_on / blocks_dir 字段的含义？若读不到，明确说"无法读取自定义字段"。
