#!/usr/bin/env bash
#SBATCH --job-name=b15c06-6-main-ediff1e-10
#SBATCH --account=ai4eccsc
#SBATCH --partition=cpu
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --mem=60G
#SBATCH --time=00:20:00
#SBATCH --chdir=/public/home/xjchen/15_Layered-Materials-Pressure-Lattice-Dynamics/case06/engine_io/jobs/6GPa/main-ediff1e-10
#SBATCH --output=/public/home/xjchen/15_Layered-Materials-Pressure-Lattice-Dynamics/case06/engine_io/jobs/logs/b15c06-6-main-ediff1e-10-%j.out
#SBATCH --error=/public/home/xjchen/15_Layered-Materials-Pressure-Lattice-Dynamics/case06/engine_io/jobs/logs/b15c06-6-main-ediff1e-10-%j.err
set -eo pipefail
source /etc/profile >/dev/null 2>&1 || true
set -u
module load vasp/6.4.1-vtst-intel
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
vasp_bin="$(command -v vasp_std)"
[[ "$vasp_bin" == /public/software/vasp/vasp.6.4.1/bin/vasp_std ]]
vasp_sha="$(sha256sum "$vasp_bin" | awk '{print $1}')"
[[ "$vasp_sha" == 14e2ac8e6b0de427ef2bff2b09a2cce7ae89010cddff59d933c45b88a5d7eae8 ]]
{
  echo "hostname=$(hostname)"
  echo "date_utc=$(date -u +%FT%TZ)"
  echo "slurm_job_id=$SLURM_JOB_ID"
  echo "pressure_GPa=6"
  echo "PSTRESS_kbar=60"
  echo "requested_NSW=1 NFREE=2 POTIM=0.015"
  echo "kz=1 ENCUT_eV=500 EDIFF_eV=1e-10"
  echo "vasp_binary=$vasp_bin"
  echo "vasp_sha256=$vasp_sha"
  echo "mpi_launcher=$(command -v mpirun) -launcher slurm -np 16"
  module list 2>&1
  cat INPUT_SHA256.txt POTCAR.identity.sha256
} > ENGINE.txt
mpirun -launcher slurm -np 16 vasp_std > vasp.stdout 2> vasp.stderr
