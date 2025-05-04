#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import subprocess
import sys
import yaml
import logging
from datetime import datetime
import time
import shutil
import os
os.nice(19)

class PerfTool:
    def __init__(self, config_file):
        self.config_file = config_file
        self.config = None
        self.output_dir = None
        self.logger = self._setup_logger()
        
    def _setup_logger(self):
        logger = logging.getLogger('perf_tool')
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger
    
    def load_config(self):
        try:
            with open(self.config_file, 'r') as file:
                self.config = yaml.safe_load(file)
                self.logger.info(f"Configuration loaded from {self.config_file}")
                
            # Set up output directory
            self.output_dir = self.config.get('output_directory', 'tmp/perf_results')
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            self.output_dir = os.path.join(self.output_dir, f"perf_run_{timestamp}")
            
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir)
                self.logger.info(f"Created output directory: {self.output_dir}")
                
            return True
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {str(e)}")
            return False
    
    def validate_config(self):
        required_keys = [
            'perf_record_frequency',
            'perf_record_duration',
            'perf_stat_duration'
        ]
        
        for key in required_keys:
            if key not in self.config:
                self.logger.error(f"Missing required configuration: {key}")
                return False
        
        return True
    
    def run_perf_record(self):
        self.logger.info("Starting perf record...")
        
        # Get configuration parameters
        frequency = self.config.get('perf_record_frequency', 99)
        duration = self.config.get('perf_record_duration', 30)
        events = self.config.get('perf_record_events', ['cycles'])
        # exclude_self = self.config.get('perf_record_exclude_self', True)
        record_workload = self.config.get('perf_record_workload', 'bench futex hash')
        
        # Build the perf record command
        output_file = os.path.join(self.output_dir, 'perf.data')
        cmd = ['perf', 'record', '-F', str(frequency)]
        
        cmd.append('-a')
        # Add events
        if events:
            # event_str = ','.join(events)
            # construct event_str to '{event_str}:S'
            event_str = '{' + ','.join(events) + '}:S'
            cmd.extend(['-e', event_str])
        
        # record call graph
        cmd.extend(['-g'])

        # record all
        cmd.extend(['-a'])

        # Exclude current process if configured
        # if exclude_self:
            # current_pid = os.getpid()
            # --exclude-pid not supported in some perf versions, try alternative approach
            # Use -p option with all pids except current one (more complex but more compatible)
            # self.logger.info(f"Note: Will attempt to exclude current process (PID: {current_pid}) with alternative method")
            # We don't add any exclusion here as the standard option doesn't work
            # Will rely on the -a (all CPUs) option which includes all processes

        # Output file
        cmd.extend(['-o', output_file])
        
        # Run for specified duration
        if duration:
            cmd.append('sleep')
            cmd.append(str(duration))
        else:
            cmd.append(record_workload)
        
        # Execute the command
        try:
            self.logger.info(f"Executing: {' '.join(cmd)}")
            process = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.logger.info("Perf record completed successfully")
            
            # Save command output
            with open(os.path.join(self.output_dir, 'perf_record_output.log'), 'w') as f:
                f.write(process.stdout.decode())
                f.write(process.stderr.decode())
            
            return output_file
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Perf record failed: {str(e)}")
            self.logger.error(f"Output: {e.stderr.decode()}")
            return None
    
    def run_perf_annotate(self, perf_data_file):
        if not self.config.get('use_perf_annotation', False):
            self.logger.info("Perf annotation disabled, skipping...")
            return True
            
        self.logger.info("Starting perf annotate...")
        
        output_file = os.path.join(self.output_dir, 'perf_annotate.txt')
        cmd = ['perf', 'annotate', '-i', perf_data_file]
        
        try:
            self.logger.info(f"Executing: {' '.join(cmd)}")
            with open(output_file, 'w') as f:
                process = subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.PIPE)
            
            self.logger.info(f"Perf annotate completed successfully, output saved to {output_file}")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Perf annotate failed: {str(e)}")
            self.logger.error(f"Output: {e.stderr.decode()}")
            return False
    
    def run_perf_stat(self):
        self.logger.info("Starting perf stat...")
        
        # Get configuration parameters
        duration = self.config.get('perf_stat_duration', 10)
        count_deltas = self.config.get('perf_stat_count_deltas', 1000)
        events = self.config.get('perf_stat_events', 
                                ['cycles', 'instructions', 'branch-misses', 
                                 'L1-dcache-load-misses', 'L1-icache-load-misses'])
        cpu_range = self.config.get('perf_stat_cpu_range', 'all')
        all_threads = self.config.get('perf_stat_all_threads', True)
        # perf_output_path = self.config.get('perf_stat_output_path', 'pef-stat.csv')
        # exclude_self = self.config.get('perf_stat_exclude_self', True)
        stat_workload = self.config.get('perf_stat_workload', 'bench futex hash')
        
        # Build the perf stat command
        output_file = os.path.join(self.output_dir, 'perf_stat.txt')
        cmd = ['perf', 'stat']
        
        # Add system-wide mode (required when using -A)
        cmd.append('-a')
        
        if count_deltas:
            cmd.extend(['-I', str(count_deltas)])
            
        # Add events
        if events:
            event_str = ','.join(events)
            cmd.extend(['-e', event_str])
        
        if cpu_range != 'all':
            # convert cpu_range from str '0-3' to list of individual cores, e.g. "0,1,2,3"
            try:
                start, end = cpu_range.split('-')
                start, end = int(start), int(end)
                cpu_list = ','.join(str(cpu) for cpu in range(start, end + 1))
                cmd.extend(['-C', cpu_list])
            except Exception as e:
                self.logger.error(f"Invalid cpu_range format: {cpu_range}")
                return False

        if all_threads:
            cmd.append('-A')
            
        # Exclude current process if configured
        # if exclude_sel:mple_config.yaml
            # current_pid = os.getpid()
            # # --exclude-pid not supported in some perf versions, try alternative approach
            # # We'll log this but won't attempt to use the unsupported option
            # self.logger.info(f"Note: Cannot exclude current process (PID: {current_pid}) as --exclude-pid is not supported")
            
        # if perf_output_path:
            # cmd.extend(['-o', perf_output_path])

        # Run for specified duration
        if duration:
            cmd.append('sleep')
            cmd.append(str(duration))
        else:
            cmd.append(stat_workload)
        
        # Execute the command
        try:
            self.logger.info(f"Executing: {' '.join(cmd)}")
            with open(output_file, 'w') as f:
                process = subprocess.run(cmd, check=True, stdout=f, stderr=subprocess.STDOUT)
            
            self.logger.info(f"Perf stat completed successfully, output saved to {output_file}")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Perf stat failed: {str(e)}")
            return False
    
    def run(self):
        if not self.load_config() or not self.validate_config():
            return False
            
        # Run perf-record
        perf_data_file = self.run_perf_record()
        if not perf_data_file:
            return False
            
        # Run perf-annotate if enabled
        if perf_data_file and not self.run_perf_annotate(perf_data_file):
            self.logger.warning("Perf annotate failed but continuing with workflow")
            
        # Run perf-stat
        if not self.run_perf_stat():
            self.logger.warning("Perf stat failed")
            
        # Save configuration used for this run
        with open(os.path.join(self.output_dir, 'config_used.yaml'), 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False)
            
        self.logger.info(f"Performance analysis completed. Results available in {self.output_dir}")
        return True

def main():
    parser = argparse.ArgumentParser(description='Performance analysis tool using Linux perf')
    parser.add_argument('-c', '--config', default='example_config.yaml', help='Path to YAML configuration file')
    args = parser.parse_args()
    
    tool = PerfTool(args.config)
    if tool.run():
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
