#!/bin/sh
threshold="${THERMAL_THROTTLING_THRESHOLD_MILLIDEG:-80000}"
profiled="/etc/profile.d/dev-limits.sh"
full_jobs="${THERMAL_THROTTLING_FULL_JOBS}"
reduced_jobs="${THERMAL_THROTTLING_REDUCED_JOBS}"

hot=0
for z in /sys/class/thermal/thermal_zone*/temp; do
  if [ -r "$z" ]; then
    read -r t < "$z"
    if [ "$t" -ge "$threshold" ] 2>/dev/null; then
      hot=1
      break
    fi
  fi
done

is_throttled=0
if [ -f "$profiled" ] && grep -q 'THERMAL_THROTTLING_ACTIVE=1' "$profiled" 2>/dev/null; then
  is_throttled=1
fi

if [ "$hot" -eq 1 ] && [ "$is_throttled" -eq 0 ]; then
  cat > "$profiled" <<EOF
export CARGO_BUILD_JOBS=${reduced_jobs}
export MAKEFLAGS=-j${reduced_jobs}
export NINJAJOBS=${reduced_jobs}
export THERMAL_THROTTLING_ACTIVE=1
EOF
fi

if [ "$hot" -eq 0 ] && [ "$is_throttled" -eq 1 ]; then
  cat > "$profiled" <<EOF
export CARGO_BUILD_JOBS=${full_jobs}
export MAKEFLAGS=-j${full_jobs}
export NINJAJOBS=${full_jobs}
EOF
fi
