import datetime
import pytz
from config import TIMEZONE

print('System UTC time:', datetime.datetime.utcnow())
print('System local time:', datetime.datetime.now())

# Check Python timezone conversion
utc_now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
local_tz = pytz.timezone(TIMEZONE)
local_now = utc_now.astimezone(local_tz)
print('UTC now:', utc_now)
print('Local now:', local_now)
print('Configured TIMEZONE:', TIMEZONE)
