/** DeepSeek 风格流式打字光标：蓝色闪烁竖线 */
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
        background: '#4D6EFE',
        borderRadius: 1,
        animation: 'chatCursorBlink 1s steps(2) infinite',
      }}
    />
  );
}
