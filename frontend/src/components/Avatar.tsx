import { useState } from 'react'
import { UserRound } from 'lucide-react'

export default function Avatar({ src, name, className = '' }: { src?: string | null; name: string; className?: string }) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  return <span className={`user-avatar ${className}`}>
    {src && src !== failedSrc ? <img src={src} alt={`${name} 的頭像`} onError={() => setFailedSrc(src)} /> : <UserRound aria-label={`${name} 的預設頭像`} />}
  </span>
}
