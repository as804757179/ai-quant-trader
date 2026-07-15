import dayjs from "dayjs";
import utc from "dayjs/plugin/utc.js";
import timezone from "dayjs/plugin/timezone.js";

const CHINA_TIMEZONE = "Asia/Shanghai";
const EXPLICIT_TIMEZONE_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/;

dayjs.extend(utc);
dayjs.extend(timezone);

export function formatChinaDateTime(value) {
  if (value == null || value === "") {
    return "待接入";
  }

  const zoned =
    typeof value === "string" && !EXPLICIT_TIMEZONE_PATTERN.test(value)
      ? dayjs.tz(value, CHINA_TIMEZONE)
      : dayjs(value).tz(CHINA_TIMEZONE);

  return zoned.isValid() ? zoned.format("YYYY-MM-DD HH:mm:ss") : "时区未知";
}
