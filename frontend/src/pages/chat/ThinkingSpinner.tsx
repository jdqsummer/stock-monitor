/** DeepSeek 风格「思考中」旋转圆圈：主题蓝圆环 + 旋转动画 + 灰色文案
 *  用于助手思考待输出（无内容、等待首个 chunk / 工具结果后文本）状态，区别于输出中的闪烁竖线光标 */
import { ds } from './theme';

export function ThinkingSpinner() {
  return (
    <span
      role="status"
      aria-label="思考中"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        color: ds.textTertiary,
        fontSize: 13,
        minHeight: 22,
      }}
    >
      <span
        style={{
          width: 16,
          height: 16,
          borderRadius: '50%',
          border: '2px solid #D6DEFF',
          borderTopColor: ds.primary,
          display: 'inline-block',
          animation: 'chatThinkingSpin 0.8s linear infinite',
        }}
      />
      思考中…
    </span>
  );
}
