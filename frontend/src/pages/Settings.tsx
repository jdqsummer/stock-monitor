import { useState, useEffect } from 'react';
import { Alert, Button, Card, Divider, Form, Input, InputNumber, Select, Space, Switch, Tabs, Tag, Tooltip, message } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { configApi } from '@/api/client';
import { brandTagStyle, status } from '@/theme';
import type { LLMModelInfo, UserConfig } from '@/types';

const VENDORS: {
  key: string; short: string; name: keyof UserConfig; label: string;
  configured: string; models: string[];
}[] = [
  { key: 'deepseek', short: 'DeepSeek', name: 'deepseek_api_key', label: 'DeepSeek API Key',
    configured: 'deepseek_api_key_configured', models: ['deepseek:deepseek-v4-flash', 'deepseek:deepseek-v4-pro'] },
  { key: 'qwen', short: 'Qwen', name: 'qwen_api_key', label: '阿里云 Qwen API Key',
    configured: 'qwen_api_key_configured', models: ['qwen:Qwen3.7-Max', 'qwen:Qwen3.8-Max'] },
  { key: 'kimi', short: 'Kimi', name: 'kimi_api_key', label: 'Kimi API Key',
    configured: 'kimi_api_key_configured', models: ['kimi:Kimi-K2.6', 'kimi:Kimi-K2.7'] },
];

export function Settings() {
  const [form] = Form.useForm();
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [configLoaded, setConfigLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('deepseek');

  // live 跟随表单：默认模型、自动分析开关、提醒开关、邮件渠道、SMTP 主机
  const defaultModel = Form.useWatch('llm_model', form) || 'openrouter:minimax/minimax-m3:free';
  const autoEnabled = Form.useWatch('analysis_auto_enabled', form);
  const remindEnabled = Form.useWatch('notification_enabled', form);
  const emailEnabled = Form.useWatch('reminder_email_enabled', form);
  const smtpHost = Form.useWatch('smtp_host', form);

  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
      setConfigLoaded(true);
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

  // 选择默认模型 → 联动切换到对应厂商 Tab（如选 Qwen3.7-Max → Qwen Tab）
  useEffect(() => {
    const v = VENDORS.find(x => x.models.includes(defaultModel));
    if (v) setActiveTab(v.key);
  }, [defaultModel]);

  const ready = models.length > 0;
  const defaultProvider = models.find(m => m.model_id === defaultModel)?.provider;
  // OpenRouter 默认模型：key 来自服务器环境变量，视为始终就绪
  const llmReady = !!(
    defaultProvider === 'openrouter' ||
    (defaultProvider && configured[`${defaultProvider}_api_key_configured`])
  );
  const llmWarning = ready && configLoaded && !llmReady;

  const handleSave = async (values: UserConfig) => {
    setLoading(true);
    try {
      const payload: Partial<UserConfig> = { ...values };
      VENDORS.forEach(({ name }) => {
        if (payload[name] === '****') delete payload[name];   // 掩码 = 不修改，提交时剔除
      });
      if (payload.smtp_password === '****') delete payload.smtp_password;
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
      <h2>系统设置</h2>

      <Card title="分析引擎状态" style={{ marginBottom: 16 }} size="small">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <div>
            当前默认模型：{ready
              ? <Tag style={brandTagStyle}>{models.find(m => m.model_id === defaultModel)?.display_name || defaultModel}</Tag>
              : '-'}
          </div>
          {ready && (llmReady
            ? <div style={{ color: status.success }}>✅ {defaultProvider === 'openrouter' ? 'OpenRouter 默认配置' : `${defaultProvider} API Key 已配置`}，LLM 深度分析可用</div>
            : llmWarning && <Alert type="warning" showIcon message="未配置 LLM API Key，股票分析将降级为纯规则计算。"
                description="请在下方「LLM 模型配置」为对应厂商填写 API Key。" />)}
        </Space>
      </Card>

      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Card title="LLM 模型配置" style={{ marginBottom: 16 }}>
          <Form.Item name="llm_model" label="默认分析模型（全局生效）">
            <Select options={models.map(m => ({ value: m.model_id, label: `${m.display_name} (${m.provider})` }))} />
          </Form.Item>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={VENDORS.map(v => ({
              key: v.key,
              label: v.short,
              children: (
                <div>
                  <Space size={4} wrap style={{ marginBottom: 16 }}>
                    {v.models.map(mid => {
                      const m = models.find(x => x.model_id === mid);
                      const isDefault = mid === defaultModel;
                      return (
                        <Tag key={mid} color={isDefault ? 'blue' : undefined}>
                          {m?.display_name || mid}{isDefault ? ' · 当前默认' : ''}
                        </Tag>
                      );
                    })}
                  </Space>
                  <Form.Item name={v.name} label={v.label}>
                    <Input.Password placeholder={configured[v.configured] ? '已配置（掩码 ****，清空不修改）' : '未配置'} />
                  </Form.Item>
                </div>
              ),
            }))}
          />
        </Card>

        <Card title="数据分析" style={{ marginBottom: 16 }}>
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
        </Card>

        <Card title="自动分析" style={{ marginBottom: 16 }}>
          <Form.Item name="analysis_auto_enabled" label="启用自动分析我的自选股（收盘后 DSH 分析并更新数据）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="analysis_schedule_afternoon" label="收盘自动分析时间">
            <Input placeholder="16:00" disabled={!autoEnabled} />
          </Form.Item>
          <Form.Item name="analysis_concurrency" label="分析并发数（同时分析的股票数，1-10）">
            <InputNumber min={1} max={10} disabled={!autoEnabled} />
          </Form.Item>
          <Alert type={llmWarning ? 'warning' : 'info'} showIcon
            message="生效于：默认分析模型 + 对应厂商 API Key、收盘时间、并发数。"
            description={llmWarning ? '当前未配置默认模型厂商的 API Key，自动分析将按规则降级执行。' : undefined} />
        </Card>

        <Card title="击球区提醒" style={{ marginBottom: 16 }}>
          <Form.Item name="notification_enabled" label="启用击球区提醒（收盘后检测进入击球区的自选股）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="reminder_email_enabled" label="邮件提醒" valuePropName="checked">
            <Switch disabled={!remindEnabled} />
          </Form.Item>
          <Form.Item name="reminder_bell_enabled" label="首页小喇叭提醒" valuePropName="checked">
            <Switch disabled={!remindEnabled} />
          </Form.Item>
          {emailEnabled && (
            <>
              <Divider>邮件服务器（留空回退全局 SMTP 配置）</Divider>
              <Form.Item name="reminder_email_recipient" label="收件邮箱（留空用注册邮箱）">
                <Input placeholder="例如 notify@example.com" disabled={!remindEnabled} />
              </Form.Item>
              <Form.Item name="smtp_host" label="SMTP 主机">
                <Input placeholder="smtp.example.com" disabled={!remindEnabled} />
              </Form.Item>
              <Form.Item name="smtp_port" label="SMTP 端口">
                <InputNumber min={1} max={65535} style={{ width: 160 }} disabled={!remindEnabled} />
              </Form.Item>
              <Form.Item name="smtp_username" label="SMTP 账号">
                <Input placeholder="发件账号" disabled={!remindEnabled} />
              </Form.Item>
              <Form.Item name="smtp_password" label="SMTP 密码">
                <Input.Password placeholder="掩码 **** 表示已配置，清空不修改" disabled={!remindEnabled} />
              </Form.Item>
              <Form.Item name="smtp_from" label="发件人地址">
                <Input placeholder="noreply@stock-monitor.local" disabled={!remindEnabled} />
              </Form.Item>
              {remindEnabled && !smtpHost && (
                <Alert type="info" showIcon message="未配置本机 SMTP，邮件提醒将回退使用全局 SMTP 配置。" />
              )}
            </>
          )}
        </Card>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>保存配置</Button>
        </Form.Item>
      </Form>
    </div>
  );
}
