#!/bin/bash
#SBATCH --job-name=p04case07-1b4461d70e
#SBATCH --chdir=/public/home/xjchen/04_Bicyclic-Peroxy-Radical-Rearrangement/case07/candidate-attempts/1b4461d70eed4d1db4a1af01b86ea882/job-001
#SBATCH --output=/public/home/xjchen/04_Bicyclic-Peroxy-Radical-Rearrangement/case07/candidate-attempts/1b4461d70eed4d1db4a1af01b86ea882/job-001/slurm-%j.out
#SBATCH --error=/public/home/xjchen/04_Bicyclic-Peroxy-Radical-Rearrangement/case07/candidate-attempts/1b4461d70eed4d1db4a1af01b86ea882/job-001/slurm-%j.err
#SBATCH --account=ai4eccsc
#SBATCH --partition=cpu
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --no-requeue
#SBATCH --cpus-per-task=1
#SBATCH --mem=16384M
#SBATCH --time=00:05:00
set +u
source /etc/profile || exit 69
module load orca/6.0.1 || exit 70
set -u
export OMPI_MCA_btl=self,vader,tcp
export OMPI_MCA_pml=ob1
P04_STAGE_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
/public/software/orca/orca_6_0_1_linux_x86-64_shared_openmpi416_avx2/orca job.inp > orca.stdout 2> orca.stderr
rc=$?
P04_STAGE_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '%s\n' "$rc" > native.exitcode
python3 -c 'import base64,json,os,sys; d=json.loads(base64.b64decode(sys.argv[1])); x={"schema":"compchemworld.p04-native-stage-receipt/v1","job_id":os.environ.get("SLURM_JOB_ID"),"stage_id":d.get("stage_id"),"started_at_utc":sys.argv[2],"ended_at_utc":sys.argv[3],"entry":sys.argv[4]}; open("native-stage-receipt.json","x").write(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n")' 'eyJjYW5kaWRhdGVfZGVjbGFyYXRpb25fc3RhdHVzIjoiY2FuZGlkYXRlX2RlY2xhcmVkX29ubHkiLCJraW5kIjoicGlsb3QiLCJyZWFzb24iOiJGaXJzdCBhY3R1YWwgbmF0aXZlIHBpbG90IGFmdGVyIGJvdW5kZWQgZXhhY3Qtb3duZWQgcmVjb25jaWxpYXRpb24gZm91bmQgbm8gZXZpZGVuY2Ugb2YgdGhlIGVhcmxpZXIgc3VibWl0IGludGVudDsgdGhpcyBwcm92aWRlciBzdGFnZSBtYXBzIHRvIGxvZ2ljYWwgcGlsb3Q6MS4iLCJyb3V0ZSI6IlVLUyBQQkUgRDNCSiBkZWYyLVNWUCBkZWYyL0ogUkkgRGVmR3JpZDMgVmVyeVRpZ2h0U0NGIEVuR3JhZCIsInN0YWdlX2lkIjoicGlsb3Q6MiJ9' "$P04_STAGE_START" "$P04_STAGE_END" job.inp
exit "$rc"
