import { format, toZonedTime } from "date-fns-tz"
import { parseISO } from "date-fns"

export function formatUTCToZone(
  isoString: string,
  zone: string,
  pattern = "yyyy-MM-dd HH:mm:ss"
) {
  const date = parseISO(isoString)
  const zoned = toZonedTime(date, zone)
  return format(zoned, pattern, { timeZone: zone })
}
