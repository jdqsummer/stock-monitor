import { useState, useEffect } from 'react';
import { Card, Form, Select, InputNumber, Input, Switch, Button, message, Divider, Tooltip } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { configApi } from '@/api/client';
import type { UserConfig, LLMModelInfo } from '@/types';

const VENDOR_KEYS: { name: keyof UserConfig; label: string; vendor: string }[] = [
  { name: 'deepseek_api_key', label: 'DeepSeek API Key', vendor: 'deepseek' },
  { name: 'qwen_api_key', label: '阿里云 Qwen API Key', vendor: 'qwen' },
  { name: 'kimi_api_key', label: 'Kimi API Key', vendor: 'kimi' },
];

export function Settings() {
  const [form] = Form.useForm();
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      form.setFieldsValue({
        ...d,
        deepseek_api_key: d.deepseek_api_key_configured ? '****' : '',
        qwen_api_key: d.qwen_api_key_configured ? '****' : '',
        kimi_api_key: d.kimi_api_key_configured ? '****' : '',
        smtp_password: d.smtp_password_configured ? '****' : '',
      });
    }).catch(() => {});
    configApi.getLLMModels().then(res => {
      setModels((res.data.data || []) as LLMModelInfo[]);
    }).catch(() => {});
  }, [form]);

  const handleSave = async (values: UserConfig) => {
    setLoading(true);
    try {
      const payload: Partial<UserConfig> = { ...values };
      VENDOR_KEYS.forEach(({ name }) => {
        if (payload[name] === '****') delete payload[name];   // 掩码 = 不修改，提交时剔除
      });
      if (payload.smtp_password === '****') delete payload.smtp_password;   // 同掩码不更新
      await configApi.update(payload as never);
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
      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Card title="LLM 模型配置" style={{ marginBottom: 16 }}>
          <Form.Item name="llm_model" label="分析模型（默认）">
            <Select options={models.map(m => ({ value: m.model_id, label: `${m.display_name} (${m.provider})` }))} />
          </Form.Item>
          <Divider>厂商 API Key（明文存储，仅用于透传 DSH 引擎分析）</Divider>
          {VENDOR_KEYS.map(k => (
            <Form.Item key={k.name} name={k.name} label={k.label}>
              <Input.Password placeholder="未配置；掩码 **** 表示已配置，清空不修改" />
            </Form.Item>
          ))}
        </Card>

        <Card title="数据更新" style={{ marginBottom: 16 }}>
          <Form.Item
            name="data_refresh_interval_minutes"
            label={<span>行情刷新间隔（分钟）
              <Tooltip title="每次刷新更新：现价、总市值、动态 PE、总股本、更新时间">
                <QuestionCircleOutlined style={{ marginLeft: 4 }} />
              </Tooltip>
            </span>}
          >
            <InputNumber min={5} max={1440} />
          </Form.Item>
          <Form.Item name="analysis_schedule_afternoon" label="收盘自动分析时间">
            <Input placeholder="16:00" />
          </Form.Item>
          <Form.Item name="analysis_auto_enabled" label="自动分析我的自选股（收盘后 DSH 分析并更新数据）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="analysis_concurrency" label="分析并发数（同时分析的股票数，1-10）">
            <InputNumber min={1} max={10} />
          </Form.Item>
        </Card>

        <Card title="击球区提醒" style={{ marginBottom: 16 }}>
          <Form.Item name="notification_enabled" label="启用击球区提醒（收盘后检测进入击球区的自选股）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="reminder_email_enabled" label="邮件提醒" valuePropName="checked" dependencies={['notification_enabled']}>
            <Switch />
          </Form.Item>
          <Form.Item name="reminder_bell_enabled" label="首页小喇叭提醒" valuePropName="checked" dependencies={['notification_enabled']}>
            <Switch />
          </Form.Item>
          <Divider>邮件服务器（留空回退全局 SMTP 配置）</Divider>
          <Form.Item name="reminder_email_recipient" label="收件邮箱（留空用注册邮箱）">
            <Input placeholder="例如 notify@example.com" />
          </Form.Item>
          <Form.Item name="smtp_host" label="SMTP 主机">
            <Input placeholder="smtp.example.com" />
          </Form.Item>
          <Form.Item name="smtp_port" label="SMTP 端口">
            <InputNumber min={1} max={65535} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="smtp_username" label="SMTP 账号">
            <Input placeholder="发件账号" />
          </Form.Item>
          <Form.Item name="smtp_password" label="SMTP 密码">
            <Input.Password placeholder="掩码 **** 表示已配置，清空不修改" />
          </Form.Item>
          <Form.Item name="smtp_from" label="发件人地址">
            <Input placeholder="noreply@stock-monitor.local" />
          </Form.Item>
        </Card>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>保存配置</Button>
        </Form.Item>
      </Form>
    </div>
  );
}
