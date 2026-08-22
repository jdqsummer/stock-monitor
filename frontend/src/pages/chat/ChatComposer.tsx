/** DeepSeek 风格输入区：居中窄列大圆角输入框 + 内嵌右下圆形发送按钮 */
import { Button, Input } from 'antd';
import { ArrowUpOutlined } from '@ant-design/icons';

const { TextArea } = Input;

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  loading: boolean;
  disabled: boolean;
}

export function ChatComposer({ value, onChange, onSend, loading, disabled }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        padding: '12px 24px 14px',
        borderTop: '1px solid #e5e5e5',
        background: '#fafafa',
      }}
    >
      <div style={{ width: '100%', maxWidth: 768 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            gap: 8,
            background: '#f7f7f7',
            border: '1px solid #e0e0e0',
            borderRadius: 14,
            padding: '6px 6px 6px 14px',
          }}
        >
          <TextArea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="问点什么，一起研究投资…"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            bordered={false}
            style={{ flex: 1, background: 'transparent', color: '#1a1a1a', fontSize: 14 }}
          />
          <Button
            type="text"
            icon={<ArrowUpOutlined />}
            onClick={() => onSend()}
            disabled={disabled}
            style={{
              background: disabled ? '#d9d9d9' : '#52c41a',
              color: '#fff',
              borderRadius: 10,
              width: 34,
              height: 34,
              flexShrink: 0,
              padding: 0,
            }}
          />
        </div>
        <div style={{ textAlign: 'center', color: '#999', fontSize: 11, marginTop: 6 }}>
          AI 分析仅供参考，不构成投资建议
        </div>
      </div>
    </div>
  );
}
