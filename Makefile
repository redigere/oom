.PHONY: setup run check status handoff clean

.setup.stamp: requirements/apt.in requirements/pip.in
	pkexec sh -c 'apt-get update && apt-get install -y $$(cat $(CURDIR)/requirements/apt.in) && apt-get autoremove -y && apt-get autoclean -y'
	xargs -a requirements/pip.in -n1 pipx install
	ansible-galaxy collection install ansible.posix
	touch .setup.stamp

setup: .setup.stamp

run: setup
	pkexec sh -c 'cd $(CURDIR) && ANSIBLE_CONFIG=ansible.cfg ansible-playbook playbook.yml'

check: setup
	pkexec sh -c 'cd $(CURDIR) && ANSIBLE_CONFIG=ansible.cfg ansible-playbook playbook.yml --check'

status:
	zramctl 2>&1; echo "exit: $$?"
	swapon --show 2>&1; echo "exit: $$?"
	@echo "earlyoom:"
	systemctl status earlyoom 2>&1; echo "exit: $$?"
	systemctl is-active systemd-oomd 2>&1; echo "exit: $$?"
	sysctl vm.swappiness vm.watermark_scale_factor vm.vfs_cache_pressure 2>&1; echo "exit: $$?"
	cat /sys/kernel/mm/lru_gen/enabled 2>&1; echo "exit: $$?"

handoff:
	python3 handoff/render.py

clean:
	pkexec sh -c 'systemctl stop earlyoom; systemctl disable earlyoom; rm -f /etc/default/earlyoom /etc/default/zramswap /etc/systemd/zram-generator.conf /etc/X11/xorg.conf.d/00-disable-dpms.conf /etc/profile.d/node_heap_limit.sh /etc/sysctl.d/99-oom-tuning.conf /etc/tmpfiles.d/mglru.conf'
