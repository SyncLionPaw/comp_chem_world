#!/usr/bin/env python3
"""Independent, bounded audit of the packaged native structures and run evidence.
Uses Python stdlib; reads only this case's public inputs and tests/evidence/native-reference.
This produces numerical science evidence, not an automatic score or decision.
"""
import csv, hashlib, json, math, re, statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
AS=ROOT/'environment/assets'
NATIVE=Path(__file__).resolve().parent
CASE=NATIVE/'results/case01'
R=0.00831446261815324 # kJ mol-1 K-1

def gro(path):
    ls=path.read_text().splitlines(); n=int(ls[1]); aa=[]
    for idx,line in enumerate(ls[2:2+n],1):
        aa.append({'id':idx,'resid':int(line[:5]),'resname':line[5:10].strip(),'name':line[10:15].strip(),'xyz':[float(line[i:i+8]) for i in (20,28,36)]})
    box=list(map(float,ls[2+n].split()))
    return aa,box

def pbc(a,b,box):
    d=[b[i]-a[i]-round((b[i]-a[i])/box[i])*box[i] for i in range(3)]
    return math.sqrt(sum(x*x for x in d))

def summ(x): return {'n':len(x),'mean':statistics.fmean(x),'sd_population':statistics.pstdev(x),'min':min(x),'max':max(x)}
def water_stats(atoms,box):
    ws=[a for a in atoms if a['resname']=='WAT']; assert len(ws)==6300
    stats={'OH1':[],'OH2':[],'HH':[],'angle_deg':[]}; residues=[]
    for i in range(0,len(ws),3):
        o,h1,h2=ws[i:i+3]
        assert (o['name'],h1['name'],h2['name'])==('O','H1','H2') and len({o['resid'],h1['resid'],h2['resid']})==1
        d1=pbc(o['xyz'],h1['xyz'],box); d2=pbc(o['xyz'],h2['xyz'],box); hh=pbc(h1['xyz'],h2['xyz'],box)
        v1=[h1['xyz'][j]-o['xyz'][j] for j in range(3)]; v2=[h2['xyz'][j]-o['xyz'][j] for j in range(3)]
        v1=[v1[j]-round(v1[j]/box[j])*box[j] for j in range(3)]; v2=[v2[j]-round(v2[j]/box[j])*box[j] for j in range(3)]
        angle=math.degrees(math.acos(max(-1,min(1,sum(v1[j]*v2[j] for j in range(3))/(d1*d2)))))
        for k,v in [('OH1',d1),('OH2',d2),('HH',hh),('angle_deg',angle)]: stats[k].append(v)
        residues.append(o['resid'])
    targets={'OH1':.09572,'OH2':.09572,'HH':.15136}
    return {'waters':len(residues),'residue_id_range':[min(residues),max(residues)],'all':{k:summ(v) for k,v in stats.items()},'target_deviation_mean_abs_nm':{k:statistics.fmean(abs(v-t) for v in stats[k]) for k,t in targets.items()},'target_deviation_max_abs_nm':{k:max(abs(v-t) for v in stats[k]) for k,t in targets.items()},'source_of_targets':'topology [ settles ]: doh=0.09572 nm, dhh=0.15136 nm'}

def topology():
    text=(AS/'topol.top').read_text().splitlines(); sections=[]; current=None
    for l in text:
        m=re.match(r'\s*\[\s*(.*?)\s*\]',l)
        if m: current=m.group(1).lower(); sections.append((current,[])); continue
        if current and l.strip() and not l.lstrip().startswith((';','#')): sections[-1][1].append(l.split(';',1)[0].split())
    molecules={}; types={}; mode=None; molname=None
    for sec,rows in sections:
        if sec=='moleculetype' and rows: molname=rows[0][0]; types[molname]={'atoms':[],'constraints':0,'bonds':[]}
        elif sec=='atoms' and molname:
            for r in rows:
                if len(r)>=8 and r[0].isdigit(): types[molname]['atoms'].append({'nr':int(r[0]),'residue':r[3],'name':r[4],'charge':float(r[6]),'mass':float(r[7])})
        elif sec=='bonds' and molname:
            types[molname]['constraints']+=sum(1 for r in rows if len(r)>=3 and r[0].isdigit())
            types[molname]['bonds'].extend(r for r in rows if len(r)>=5 and r[0].isdigit())
        elif sec=='constraints' and molname:
            types[molname]['constraints']+=sum(1 for r in rows if len(r)>=3 and r[0].isdigit())
        elif sec=='settles' and molname:
            types[molname]['settles']=rows
        elif sec=='molecules':
            for r in rows:
                if len(r)>=2 and r[1].isdigit(): molecules[r[0]]=int(r[1])
    summtypes={}
    atoms_n=0; qtot=0
    for name,nm in molecules.items():
        typ=types[name]; n=len(typ['atoms'])*nm; q=math.fsum(a['charge'] for a in typ['atoms'])*nm; atoms_n+=n; qtot+=q
        summtypes[name]={'molecule_count':nm,'atoms_per_molecule':len(typ['atoms']),'system_atoms':n,'charge_per_molecule_e':math.fsum(a['charge'] for a in typ['atoms']),'system_charge_e':q,'atom_names_in_topology_order':[a['name'] for a in typ['atoms']],'topology_bond_terms_converted_by_all_bonds':typ['constraints'] if name!='WAT' else 0,'settles':typ.get('settles')}
    # Convert non-water bond terms to constraints because mdp sets constraints=all-bonds; water uses SETTLE.
    return {'molecules':summtypes,'total_atoms':atoms_n,'total_formal_charge_e':qtot,'source':'topol.top parsed [atoms]/[molecules]; MOL/OCB [bonds] terms converted by actual all-bonds MDP; FLEXIBLE undefined, so WAT uses SETTLE, not the conditional flexible [bonds] section','mdp_constraint_setting':'all-bonds; algorithm LINCS; iter=2; order=4'}

def bond_geometry(atoms,box,topo,label):
    by={(a['resname'],a['name']):a for a in atoms}
    toptext=(AS/'topol.top').read_text(); mol=None; section=None; bonds={'MOL':[],'OCB':[]}
    for line in toptext.splitlines():
        h=re.match(r'\s*\[\s*(.*?)\s*\]',line)
        if h:
            section=h.group(1).lower()
            if section=='moleculetype': mol=None
            continue
        if not line.strip() or line.lstrip().startswith(';'): continue
        row=line.split(';',1)[0].split()
        if section=='moleculetype':
            mol=row[0] if row else None
        elif section=='bonds' and mol in bonds and len(row)>=5 and row[0].isdigit():
            bonds[mol].append(row)
    out={}
    for m,rows in bonds.items():
        mol_atoms=[a for a in atoms if a['resname']==m]; names={i+1:a['name'] for i,a in enumerate(mol_atoms)}; local={i+1:a for i,a in enumerate(mol_atoms)}; dev=[]
        for r in rows:
            i,j=int(r[0]),int(r[1]); target_nm=float(r[3]); ai=local[i]; aj=local[j]; actual=pbc(ai['xyz'],aj['xyz'],box)
            dev.append({'atom_ids':[ai['id'],aj['id']],'atom_names':[ai['name'],aj['name']],'actual_nm':actual,'topology_equilibrium_nm':target_nm,'delta_nm':actual-target_nm})
        ds=[x['delta_nm'] for x in dev]
        out[m]={'bond_terms':len(ds),'rms_delta_nm':math.sqrt(statistics.fmean(x*x for x in ds)),'max_abs_delta_nm':max(abs(x) for x in ds),'max_abs_pair':max(dev,key=lambda x:abs(x['delta_nm']))}
    return out

def contact_min(a,b,box):
    # Only explicit cross-selection pairs; bounded about (224 atoms x 6309 WAT atoms), never full N^2.
    best=(float('inf'),None,None); q10=[]
    for x in a:
        for y in b:
            d=pbc(x['xyz'],y['xyz'],box)
            if d<best[0]: best=(d,x,y)
            if d<0.20: q10.append((d,x,y))
    def atom(x): return {'id':x['id'],'resid':x['resid'],'resname':x['resname'],'name':x['name']}
    return {'pair_evaluations':len(a)*len(b),'minimum_nm':best[0],'atoms':{'first':atom(best[1]),'second':atom(best[2])},'pairs_below_0.20nm_count':len(q10),'warning':'0.20 nm is only a report bin, not a pass/fail cutoff; bonded exclusions are not removed for these intermolecular selections'}

def water_oxygen_min(oxygen,box):
    # Periodic cell list; stop only when best pair is shorter than a full cell width, bounding all unsearched bins.
    n=[max(1,int(L/0.5)) for L in box]; w=[box[i]/n[i] for i in range(3)]; cells={}
    def cell(a): return tuple(int(a['xyz'][i]/w[i])%n[i] for i in range(3))
    for a in oxygen: cells.setdefault(cell(a),[]).append(a)
    by_id={a['id']:a for a in oxygen}; best=(float('inf'),None,None); pairs=0
    for a in oxygen:
        c=cell(a); cand=set()
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    key=((c[0]+dx)%n[0],(c[1]+dy)%n[1],(c[2]+dz)%n[2])
                    for b in cells.get(key,[]):
                        if b['id']>a['id']: cand.add(b['id'])
        for bid in cand:
            b=by_id[bid]; d=pbc(a['xyz'],b['xyz'],box); pairs+=1
            if d<best[0]: best=(d,a,b)
    if best[0]>=min(w): raise RuntimeError('no nearest pair inside one-cell exactness bound')
    def atom(x): return {'id':x['id'],'resid':x['resid'],'resname':x['resname'],'name':x['name']}
    return {'selection':'WAT oxygen atoms only; different molecules; PBC minimum image','evaluated_candidate_pairs':pairs,'exhaustive_pairs':len(oxygen)*(len(oxygen)-1)//2,'search':'periodic spatial cell list; minimum is shorter than one cell width, bounding unsearched bins','minimum_nm':best[0],'atoms':{'first':atom(best[1]),'second':atom(best[2])}}

def xvg(path):
    rows=[]
    for l in path.read_text().splitlines():
        if not l.strip() or l.lstrip()[0] in '#@&': continue
        rows.append([float(x) for x in l.split()])
    return rows

def acf_summary(x):
    # Initial-positive-pair (Geyer style) rough diagnostic; report method because 50 ps finite.
    y=[v-statistics.fmean(x) for v in x]; n=len(y); var=math.fsum(v*v for v in y)/n
    if not var: return {'tau_int_samples':0.5,'tau_int_ps':0.05,'effective_samples_approx':n}
    rho=[]
    for lag in range(min(n//2,200)):
        rho.append(math.fsum(y[i]*y[i+lag] for i in range(n-lag))/((n-lag)*var))
    tau=.5
    for k in range(1,len(rho)-1,2):
        pair=rho[k]+rho[k+1]
        if pair<=0: break
        tau+=pair
    return {'tau_int_samples':tau,'tau_int_ps':tau*0.1,'effective_samples_approx':n/(2*tau),'method':'truncated positive pair sum of normalized sample ACF; descriptive only, 501 correlated samples'}

def linear_fit(xs,ys):
    xm=statistics.fmean(xs); ym=statistics.fmean(ys); denom=math.fsum((x-xm)**2 for x in xs); slope=math.fsum((x-xm)*(y-ym) for x,y in zip(xs,ys))/denom
    return {'slope_kJ_mol_ps':slope,'intercept_kJ_mol':ym-slope*xm,'first_value_kJ_mol':ys[0],'last_value_kJ_mol':ys[-1],'endpoint_change_kJ_mol':ys[-1]-ys[0],'n':len(xs)}

def main():
    source_provenance=NATIVE/'gromacs-sources.json'
    topo=topology(); result={'audit_version':2,'purpose':'evidence audit only; no scoring threshold/COMPLETE status change','sources':{'gromacs_md_2022.6':'https://manual.gromacs.org/documentation/2022.6/reference-manual/algorithms/molecular-dynamics.html (kinetic temperature, degrees of freedom, neighbor-list timing)','gromacs_groups_2022.6':'https://manual.gromacs.org/documentation/2022.6/reference-manual/algorithms/group-concept.html (temperature coupling groups)','gromacs_constraints_2022.6':'https://manual.gromacs.org/documentation/2022.6/reference-manual/algorithms/constraint-algorithms.html (LINCS/SETTLE)','gromacs_mdp_2022.6':'https://manual.gromacs.org/documentation/2022.6/user-guide/mdp-options.html (define controls FLEXIBLE water branch)','Bussi_2007':'https://doi.org/10.1063/1.2408420','Hess_LINCS_1997':'https://doi.org/10.1002/(SICI)1096-987X(199709)18:12%3C1463::AID-JCC4%3E3.0.CO;2-H','Miyamoto_Kollman_SETTLE_1992':'https://doi.org/10.1002/jcc.540130805'},'input_hashes':{},'source_provenance_file':'gromacs-sources.json','source_provenance_sha256':hashlib.sha256(source_provenance.read_bytes()).hexdigest(),'retrieved_source_records':json.loads(source_provenance.read_text())['items'],'initial_structures':{},'topology':topo,'contact_audit':{},'runtime_dof_temperature':{},'energy_and_autocorrelation':{},'limits':[]}
    result['sources_bibliography']={'Bussi_2007':'doi:10.1063/1.2408420 (bibliographic context only; not used as evidence basis)','Hess_LINCS_1997':'doi:10.1002/(SICI)1096-987X(199709)18:12<1463::AID-JCC4>3.0.CO;2-H (bibliographic context only)','Miyamoto_Kollman_SETTLE_1992':'doi:10.1002/jcc.540130805 (bibliographic context only)'}
    for file in ['b.gro','u.gro','topol.top','NVT-50ps-dt1fs.mdp','NVT-50ps-dt2fs.mdp']:
        result['input_hashes'][file]=hashlib.sha256((AS/file).read_bytes()).hexdigest()
    processed=[]
    for run in ['B-dt1fs','B-dt2fs','U-dt1fs','U-dt2fs']:
        p=CASE/'runs'/run/'processed.top'; text=p.read_text(); digest=hashlib.sha256(p.read_bytes()).hexdigest()
        assert '[ settles ]' in text and text.count('[ settles ]')==1
        # Count active WAT bonds/settles from the preprocessed molecule block, not the #ifdef FLEXIBLE source branch.
        sec=None; mol=None; bond_counts={name:0 for name in topo['molecules']}; settle_rows={name:[] for name in topo['molecules']}
        for line in text.splitlines():
            h=re.match(r'\s*\[\s*(.*?)\s*\]',line)
            if h: sec=h.group(1).lower(); continue
            if not line.strip() or line.lstrip().startswith(';'): continue
            row=line.split(';',1)[0].split()
            if sec=='moleculetype': mol=row[0] if row else None
            elif mol in bond_counts and sec=='bonds' and row and row[0].isdigit(): bond_counts[mol]+=1
            elif mol in settle_rows and sec=='settles' and row and row[0].isdigit(): settle_rows[mol].append(row)
        assert bond_counts=={'MOL':30,'OCB':216,'Na+':0,'WAT':0}
        assert len(settle_rows['WAT'])==1 and settle_rows['WAT'][0][2:4]==['0.09572000','0.15136000']
        processed.append({'run':run,'sha256':digest,'active_bond_terms_by_molecule':bond_counts,'active_settle_rows_by_molecule':settle_rows})
    assert len({x['sha256'] for x in processed})==1
    active_bonds=processed[0]['active_bond_terms_by_molecule']; settle_defs=processed[0]['active_settle_rows_by_molecule']
    active_counts={m:active_bonds[m]*topo['molecules'][m]['molecule_count'] for m in active_bonds}
    active_counts['WAT']=3*len(settle_defs['WAT'])*topo['molecules']['WAT']['molecule_count']
    total_constraints=sum(active_counts.values()); expected_dof=3*topo['total_atoms']-total_constraints-3
    result['processed_topology_audit']={'per_run':processed,'all_four_same_sha256':True,'active_constraint_counts':active_counts,'total_active_constraints':total_constraints,'dof_count_check':{'cartesian':3*topo['total_atoms'],'constraints_from_active_processed_top':total_constraints,'linear_COM_removed':3,'expected_total_DOF':expected_dof},'basis':'Counts and SETTLE geometry parsed from each actual grompp processed.top; all-bonds mdp semantics convert the remaining listed MOL/OCB bonds to constraints; compared with production grompp group-DOF sums'}
    for label in ['b','u']:
        aa,box=gro(AS/f'{label}.gro'); counts={}
        for a in aa: counts[a['resname']]=counts.get(a['resname'],0)+1
        assert len(aa)==6533 and counts=={'MOL':28,'OCB':196,'Na+':9,'WAT':6300}
        name_validation={}
        for typ in topo['molecules']:
            got=[a['name'] for a in aa if a['resname']==typ]
            expected=topo['molecules'][typ]['atom_names_in_topology_order']
            name_validation[typ]=got[:len(expected)]==expected
            assert name_validation[typ]
        water=water_stats(aa,box)
        group_host=[a for a in aa if a['resname']=='OCB']; guest=[a for a in aa if a['resname']=='MOL']; wat=[a for a in aa if a['resname']=='WAT']; ions=[a for a in aa if a['resname']=='Na+']; waters_oxygen=[a for a in wat if a['name']=='O']
        result['initial_structures'][label]={'atoms':len(aa),'residue_atom_counts':counts,'box_nm':box,'water_geometry_all_2100':water,'host_guest_bond_geometry':bond_geometry(aa,box,topo,label),'topology_atom_order_matches_gro':name_validation,'coordinate_pairwise_comparison':'see gro source coordinates; no force-field overlap thresholds sourced'}
        result['contact_audit'][label]={'host_OCB_vs_water_atoms':contact_min(group_host,wat,box),'guest_MOL_vs_water_atoms':contact_min(guest,wat,box),'host_OCB_vs_guest_MOL':contact_min(group_host,guest,box),'water_vs_ions':contact_min(wat,ions,box),'water_oxygen_vs_water_oxygen':water_oxygen_min(waters_oxygen,box)}
    # DOF parsed from actual grompp logs per production run; cross-check printed MDP temperature groups.
    for run in ['B-dt1fs','B-dt2fs','U-dt1fs','U-dt2fs']:
        d=CASE/'runs'/run; log=(d/'grompp.log').read_text(); mdp=(d/'mdout.mdp').read_text()
        dofs={g:float(v) for g,v in re.findall(r'Number of degrees of freedom in T-Coupling group (.+?) is ([0-9.]+)',log)}
        gt={}
        result['runtime_dof_temperature'][run]={'dof_from_real_grompp_log':dofs,'tc_grps_from_mdout_mdp':re.search(r'^tc-grps\s*=\s*(.*)$',mdp,re.M|re.I).group(1).split(),'grompp_version':next((l.strip() for l in log.splitlines() if 'GROMACS - gmx grompp' in l),'')}
        rows=xvg(CASE/'analysis/energy'/run/'energy.xvg')
        result['energy_and_autocorrelation'][run]={}
        legends=re.findall(r'@\s+s(\d+)\s+legend\s+"([^"]+)"',(CASE/'analysis/energy'/run/'energy.xvg').read_text())
        name_idx={name:int(i)+1 for i,name in legends}
        # Group DOFs from grompp and group temperature energy series; infer per-group kinetic energy from T*DOF*kB/2.
        temps={name:[r[name_idx[name]] for r in rows] for name in ('Temperature','T-OCB','T-MOL','T-Water_and_ions')}
        kglobal=[r[name_idx['Kinetic En.']] for r in rows]
        result['runtime_dof_temperature'][run]['temperature_series_means_K']={k:statistics.fmean(v) for k,v in temps.items()}
        result['runtime_dof_temperature'][run]['temperature_series_population_sd_K']={k:statistics.pstdev(v) for k,v in temps.items()}
        result['runtime_dof_temperature'][run]['canonical_equilibrium_sd_reference_K']={g:300*math.sqrt(2/f) for g,f in dofs.items()}
        result['runtime_dof_temperature'][run]['canonical_sd_scope']='equilibrium canonical scale reference only; observed finite 50 ps series are correlated and not tested against a hard cutoff'
        dof_sum=math.fsum(dofs.values()); result['runtime_dof_temperature'][run]['grompp_total_dof_sum']=dof_sum
        result['runtime_dof_temperature'][run]['matches_topology_constraint_count']=abs(dof_sum-result['processed_topology_audit']['dof_count_check']['expected_total_DOF'])<0.02
        assert result['runtime_dof_temperature'][run]['matches_topology_constraint_count']
        implied=[]
        for i in range(len(rows)):
            implied.append(math.fsum(0.5*R*dofs[g]*rows[i][name_idx['T-'+g.replace('Water_and_ions','Water_and_ions')]] for g in dofs))
        result['energy_and_autocorrelation'][run]={'n_energy_samples':len(rows),'sample_interval_ps':rows[1][0]-rows[0][0],'kinetic_energy_global_mean_kJmol':statistics.fmean(kglobal),'sum_group_kinetic_from_T_DOF_mean_kJmol':statistics.fmean(implied),'max_abs_global_vs_group_derived_KE_kJmol':max(abs(a-b) for a,b in zip(kglobal,implied)),'time_blocks_0_25_25_50ps':{k:{'0-25ps_mean':statistics.fmean([r[name_idx[k]] for r in rows if 0<=r[0]<25]),'25-50ps_mean':statistics.fmean([r[name_idx[k]] for r in rows if 25<=r[0]<=50])} for k in ('Temperature','Potential','Kinetic En.','Total Energy','Conserved En.','Constr. rmsd','T-OCB','T-MOL','T-Water_and_ions')},'temperature_and_energy_acf':{key:acf_summary([r[name_idx[key]] for r in rows]) for key in ('Temperature','Potential','Total Energy','Conserved En.','T-OCB','T-MOL','T-Water_and_ions')},'conserved_energy_ols_trend':{'0-50ps':linear_fit([r[0] for r in rows],[r[name_idx['Conserved En.']] for r in rows]),'5-50ps_sensitivity':linear_fit([r[0] for r in rows if r[0]>=5],[r[name_idx['Conserved En.']] for r in rows if r[0]>=5])},'conserved_energy_interpretation':'GROMACS conserved-energy diagnostic under thermostat, not NVE total-energy conservation. Slope/endpoint are descriptive signals; no hard acceptance threshold applied.'}
    result['limits']=['No threshold for a closest contact was available from a source; distances are reported, not classified as clashes.','Initial-state full water geometry does not replace production trajectory geometry. The earlier trajectory analysis sampled only 20 fixed waters; all 2100 initial waters are analyzed here.','The existing production trajectories are a single matched-seed pair per B/U and 50 ps each; this audit does not show equilibration or uncertainty convergence.','ACF/ESS estimates over 50 ps are descriptive and unstable for slowly varying components.','This audit does not authorize or launch more MD.']
    out=Path(__file__).with_name('audit.json'); out.write_text(json.dumps(result,indent=2,ensure_ascii=False,default=lambda x:list(x) if isinstance(x,set) else x)+'\n'); print('Wrote',out)
    print(json.dumps({'charge':topo['total_formal_charge_e'],'molecule_counts':{k:v['molecule_count'] for k,v in topo['molecules'].items()},'water_summary':{k:v['water_geometry_all_2100']['all'] for k,v in result['initial_structures'].items()},'contact_mins':{k:{g:v['minimum_nm'] for g,v in x.items()} for k,x in result['contact_audit'].items()},'ke_diff_max':{k:v['max_abs_global_vs_group_derived_KE_kJmol'] for k,v in result['energy_and_autocorrelation'].items()}},indent=2))
if __name__=='__main__': main()
