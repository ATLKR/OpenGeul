/** Resolve the format from the requested filename, never from a renamed byte stream. */
export type SaveFormat = 'hwp' | 'hwpx';
export function resolveSavePath(path: string, fallback: SaveFormat): {path: string; format: SaveFormat} {
  const name = path.split(/[\\/]/).pop() ?? '';
  if (!name.trim() || /[\x00-\x1f]/.test(path) || /[.\s]$/.test(name)) {
    throw new Error('유효한 문서 파일 이름을 입력하세요.');
  }
  const suffix = /\.([^.]+)$/.exec(name)?.[1]?.toLowerCase();
  if (suffix === 'hwp' || suffix === 'hwpx') return {path, format: suffix};
  if (suffix) throw new Error('저장 형식은 .hwp 또는 .hwpx여야 합니다.');
  return {path: `${path}.${fallback}`, format: fallback};
}
