#!/usr/bin/env python3
"""Inspect the native TPR's SETTLE-water exclusion block without loading MD."""
import argparse, hashlib, json
from pathlib import Path
import MDAnalysis as mda
from MDAnalysis.topology.tpr import utils

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
    return h.hexdigest()

def audit(tpr):
    blocks=[]
    def capture(data):
        n=data.unpack_int(); total=data.unpack_int()
        index=list(map(int,utils.ndo_int(data,n+1)))
        excluded=list(map(int,utils.ndo_int(data,total)))
        blocks.append({"n_atoms_with_exclusion_rows":n,"n_exclusion_entries":total,"row_index":index,"excluded_local_indices":excluded})
        return n,total
    old=utils.do_blocka
    utils.do_blocka=capture
    try:
        u=mda.Universe(str(tpr))
    finally:
        utils.do_blocka=old
    names=u.atoms.names.tolist(); q=u.atoms.charges.tolist(); nat=len(names)
    water=(nat==27099 and len(u.residues)==9033 and all(names[i:i+3]==["OW","HW1","HW2"] for i in range(0,nat,3)))
    charge=water and all(abs(q[i]+.8476)<2e-4 and abs(q[i+1]-.4238)<2e-4 and abs(q[i+2]-.4238)<2e-4 for i in range(0,nat,3))
    allpairs=[]
    for block in blocks:
        ids=block["excluded_local_indices"]; ix=block["row_index"]
        if len(ix)!=4 or len(ids)!=ix[-1]:
            allpairs.append(False); continue
        rows=[set(ids[ix[i]:ix[i+1]]) for i in range(3)]
        allpairs.append(all(j in rows[i] for i in range(3) for j in range(3) if i!=j))
    excluded=bool(blocks) and all(allpairs)
    bonds=u.bonds.indices
    settle_bonds=(len(bonds)==2*9033 and all(bonds[i:i+2].tolist()==[[3*w,3*w+1],[3*w,3*w+2]] for w,i in enumerate(range(0,len(bonds),2))))
    return {"tpr":str(tpr),"sha256":sha(tpr),"atoms":nat,"waters":len(u.residues),"atom_order_and_count_pass":bool(water),"SPC_E_charges_pass":bool(charge),"settle_bond_pairs":int(len(bonds)),"settle_bond_layout_pass":bool(settle_bonds),"molecule_exclusion_blocks":blocks,"all_intramolecular_nonbonded_pairs_excluded":excluded,"status":"PASS" if water and charge and settle_bonds and excluded else "FAIL"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("tpr"); ap.add_argument("--json",default="")
    args=ap.parse_args(); result=audit(Path(args.tpr)); out=json.dumps(result,indent=2)+"\n"
    if args.json: Path(args.json).write_text(out)
    print(out,end="")
    if result["status"]!="PASS": raise SystemExit(2)

if __name__=="__main__": main()
