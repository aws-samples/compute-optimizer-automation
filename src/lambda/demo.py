from datetime import datetime, timedelta

day_of_week = "Wednesday"
hour_str = "03:00"

hour = datetime.strptime(hour_str, "%H:%M").time()
weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
weekday = weekdays.index(day_of_week)
now = datetime.utcnow()
days_until_weekday = (7 + weekday - now.weekday()) % 7
if days_until_weekday == 0 and now.time() > hour:
    days_until_weekday = 7
    
time_until_weekday = timedelta(days=days_until_weekday)
next_weekday = now + time_until_weekday
next_weekday = next_weekday.replace(hour=hour.hour, minute=hour.minute, second=0, microsecond=0)
utc_timestamp = next_weekday.strftime("%Y-%m-%dT%H:%M:%SZ")
print("The next occurrence of", day_of_week, "at", hour_str + " UTC is on", utc_timestamp)
