// Installed fonts only. Never claim a downloaded alias is the document's original font.
export interface FontEntry { name: string; file: string; format?: 'woff2' | 'woff'; unicodeRange?: string }
export const FONT_LIST: readonly FontEntry[] = [];
export const REGISTERED_FONTS = new Set<string>();
