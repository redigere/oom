.PHONY: help setup run check status handoff clean

help:
	@echo "help: Show this help message"
	@echo "setup: Install dependencies"
	@echo "run: Apply Ansible playbook"
	@echo "check: Run Ansible playbook in check mode (dry-run)"
	@echo "status: Print system status and config"
	@echo "handoff: Render handoff documents"
	@echo "clean: Remove installed configuration files"

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

clean: setup
	pkexec sh -c 'cd $(CURDIR) && ANSIBLE_CONFIG=ansible.cfg ansible-playbook restore.yml'
