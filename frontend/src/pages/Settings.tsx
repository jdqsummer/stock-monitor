import { useState, useEffect } from 'react';
import { Card, Form, Select, InputNumber, Input, Switch, Button, message, Divider } from 'antd';
import { configApi } from '@/api/client';
import type { UserConfig, LLMModelInfo } from '@/types';

export function Settings() {
  const [form] = Form.useForm();
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    configApi.get().then(res => {
      form.setFieldsValue(res.data.data);
    }).catch(() => { /* 配置加载失败 */ });
    configApi.getLLMModels().then(res => {
      setModels((res.data.data || []) as LLMModelInfo[]);
    }).catch(() => { /* 模型列表加载失败 */ });
  }, []);

  const handleSave = async (values: UserConfig) => {
    setLoading(true);
    try {
      await configApi.update(values);
      message.success('配置已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>⚙️ 系统设置</h2>

      <Card title="LLM 模型配置" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical" onFinish={handleSave}
          initialValues={{ llm_model: 'deepseek-chat', llm_temperature: 0.3, llm_max_tokens: 4096 }}>
          <Form.Item name="llm_model" label="分析模型">
            <Select options={models.map(m => ({
              value: m.model_id,
              label: `${m.display_name} (${m.provider})`,
            }))} />
          </Form.Item>
          <Form.Item name="llm_temperature" label="Temperature">
            <InputNumber min={0} max={2} step={0.1} />
          </Form.Item>
          <Form.Item name="llm_max_tokens" label="Max Tokens">
            <InputNumber min={1} max={32768} step={256} />
          </Form.Item>

          <Divider>数据更新</Divider>

          <Form.Item name="data_refresh_interval_minutes" label="监控刷新间隔（分钟）">
            <InputNumber min={5} max={1440} />
          </Form.Item>
          <Form.Item name="analysis_schedule_morning" label="早盘分析时间">
            <Input placeholder="09:30" />
          </Form.Item>
          <Form.Item name="analysis_schedule_afternoon" label="收盘分析时间">
            <Input placeholder="15:30" />
          </Form.Item>
          <Form.Item name="analysis_auto_enabled" label="自动分析我的自选股（每日）" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Divider>投资偏好</Divider>

          <Form.Item name="investment_style" label="投资风格">
            <Select options={[
              { value: 'value', label: '价值投资' },
              { value: 'growth', label: '成长投资' },
              { value: 'balanced', label: '均衡' },
            ]} />
          </Form.Item>
          <Form.Item name="risk_tolerance" label="风险承受度">
            <Select options={[
              { value: 'conservative', label: '保守' },
              { value: 'moderate', label: '稳健' },
              { value: 'aggressive', label: '激进' },
            ]} />
          </Form.Item>
          <Form.Item name="notification_enabled" label="击球区提醒" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading}>保存配置</Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
