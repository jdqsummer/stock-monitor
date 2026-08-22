/** DeepSeek 风格流式打字光标：闪烁竖线 */
export function TypingCursor() {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: 8,
        height: 18,
        marginLeft: 2,
        verticalAlign: 'text-bottom',
        background: '#52c41a',
        borderRadius: 1,
        animation: 'chatCursorBlink 1s steps(2) infinite',
      }}
    />
  );
}
