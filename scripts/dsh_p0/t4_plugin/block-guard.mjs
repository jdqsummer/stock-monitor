// 运行时版本：block-guard.ts 的编译产物。
export const name = 'block-guard'
export const inject = ['tools']

export function apply(ctx) {
  ctx.tools.guard((execution) => {
    if (execution.name === 'hello_echo') {
      return 'hello_echo 已被 block-guard 守卫拒绝（单调否决，不可逆）'
    }
    return undefined
  })
}
