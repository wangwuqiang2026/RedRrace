// 真接口客户端（VITE_USE_MOCK=0 时使用）。/api/ask 当前为 501 占位（阶段三实现），
// 壳阶段仅保证类型打通与错误处理；**请求体的蛇形字段构造也收敛到 adapter.toAskRequest**
// （N-2/review-F2：裁决 4 的「单层」口径覆盖读与写，本文件不再出现任何契约字段名）。
import type { AnswerModel } from './model'
import { toAnswerModel, toAskRequest } from './adapter'

export async function askApi(
  question: string,
  opts: { topK?: number; role?: '学生' | '教师' | '馆员' } = {},
  signal?: AbortSignal,
): Promise<AnswerModel> {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(toAskRequest(question, opts)),
    signal,
  })
  if (!res.ok) {
    // 技术故障（非内容拒答）：交由界面 error 态渲染「⊗ + 重试」（§5.4 降级矩阵）。
    // 护栏（§3.2 分界定稿）：status=200 && refusal=true 是**正常回答形态**，
    // 任何情况下不得在此 throw、不得走本节红色版式。
    throw new Error(`接口失败：HTTP ${res.status}`)
  }
  return toAnswerModel(await res.json())
}
