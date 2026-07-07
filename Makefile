.PHONY: setup setup-apt setup-pip run check status handoff clean

setup-apt:
	sudo apt-get update && sudo apt-get install -y $$(cat requirements/apt.in) && sudo apt-get autoremove -y && sudo apt-get autoclean -y

setup-pip:
	pip3 install --upgrade $$(cat requirements/pip.in) && pip3 cache purge

setup: setup-apt setup-pip
	ansible-galaxy collection install ansible.posix

run: setup
	ansible-playbook playbook.yml

check: setup
	ansible-playbook playbook.yml --check

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
	sudo systemctl stop earlyoom; sudo systemctl disable earlyoom
	sudo rm -f /etc/default/earlyoom
	sudo rm -f /etc/default/zramswap /etc/systemd/zram-generator.conf
	sudo rm -f /etc/profile.d/node_heap_limit.sh
	sudo rm -f /etc/sysctl.d/99-oom-tuning.conf
	sudo rm -f /etc/tmpfiles.d/mglru.conf
