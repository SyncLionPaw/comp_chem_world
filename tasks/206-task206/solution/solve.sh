#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = 'e453515c717d3d06ff26d3f9244fac2baf691b492aece515dd4fba51c1c06b61'

from pathlib import Path
import base64, hashlib, os, shutil, subprocess, sys, tempfile

def decode_bundle(source, target):
    import base64, hashlib, json
    digest = hashlib.sha256()
    with source.open('r', encoding='utf-8') as stream, target.open('wb') as output:
        header = []
        for line in stream:
            if line.strip() == '"chunks": [':
                metadata = json.loads(''.join(header) + '"chunks": []}')
                break
            header.append(line)
        else:
            raise ValueError('Missing reference payload')
        if metadata.get('encoding') != 'tar+gzip;base64':
            raise ValueError('Unsupported reference encoding')
        for line in stream:
            text = line.strip()
            if text == ']':
                break
            value = json.loads(text.removesuffix(','))
            if not isinstance(value, str):
                raise ValueError('Invalid reference block')
            data = base64.b64decode(value, validate=True)
            digest.update(data)
            output.write(data)
        else:
            raise ValueError('Incomplete reference payload')
        if stream.read().strip() != '}':
            raise ValueError('Invalid reference ending')
    if digest.hexdigest() != metadata.get('sha256'):
        raise ValueError('Reference archive integrity failure')

def unpack(archive, destination):
    import os, shutil, tarfile
    from pathlib import PurePosixPath
    with tarfile.open(archive, mode='r|gz') as bundle:
        for member in bundle:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                raise ValueError('Unsafe reference path')
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                os.chmod(target, member.mode & 0o777)
            else:
                raise ValueError('Unsupported reference entry')

script = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='reference-solution-') as directory:
    temporary = Path(directory)
    archive = temporary / 'solution.tar.gz'
    digest = hashlib.sha256()
    with script.open() as source, archive.open('wb') as output:
        for line in source:
            if line.rstrip() == '# SOLUTION_DATA':
                break
        else:
            raise ValueError('Reference solution payload missing')
        for line in source:
            if not line.startswith('# '):
                raise ValueError('Invalid reference solution payload')
            data = base64.b64decode(line[2:].strip(), validate=True)
            digest.update(data)
            output.write(data)
    if digest.hexdigest() != EXPECTED:
        raise ValueError('Reference solution archive integrity failure')
    in_container = script.parent == Path('/solution')
    root = Path('/') if in_container else temporary / 'workspace'
    root.mkdir(exist_ok=True)
    backup = temporary / 'entry.sh'
    if in_container:
        shutil.copy2(script, backup)
    try:
        unpack(archive, root)
        result = subprocess.run(['bash', str(root / 'solution' / 'solve.sh'), *sys.argv[2:]], env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    finally:
        if in_container:
            # Only remove files from this reference payload, not user outputs.
            with tarfile.open(archive, 'r:gz') as bundle:
                paths = sorted([root / x.name for x in bundle.getmembers() if x.isfile()], key=lambda p: len(p.parts), reverse=True)
            for path in paths:
                path.unlink(missing_ok=True)
            for path in sorted(script.parent.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir():
                    try: path.rmdir()
                    except OSError: pass
            shutil.copy2(backup, script)
    raise SystemExit(result.returncode)

PY
# SOLUTION_DATA
# H4sICAAAAAAA/3NvbHV0aW9uLnRhcgDtfWtzG8eV6H7mr5gd160MZGAIkKIs08tUaIl2lA1lWdI+KljuZIBpACMOZqCZAUVapSr5qUfkyNm1Izu2V/ZNNvbNxpKT3JuVLdmuyg+4P2KXIKlP/gv3nH7PAyD92Nz9gHFZBGa6T58+ffq8e5BEwTD1o3A2it12QJx4GNqDrb/4Vq86XEcOH6Z/4cr9fWy+oe6x+425+bmFvzDq3y4a5dcwSd0Yhv9zjPXf8DJN85lOx2/7bmDEpENiEraJkXCuMDpRbLTdhNTqR2ppFCdwrzZwY7dPUhLXoIOf2jMzp/FvYrhG0neDwEhIakQdg2z6SeqHXeOM2yXGqTgakNjgQIx1Q4KBjl3XD5PUSHtkZjBsBX7bSGO4hZ2fXTVISOLuluH5HY5fYgxDD4DFvgeQY9IdBm7sP+ciylVjmGA/hEU23XZqdABQSozvu30/SKPQd0PAMEz81N/wUwBLEr8bGtYQWtUALRKnw7hFYSU4DQAEQ7jBTEzacCuNh+2UeEaylaSkn1SNZwYkXF01TkvieRFMgRgDaO/jXCtVhBEaG27ge24K2CNuQDEE0/FJ4FUNwGkYyokgeKCNorQBI6dxFEA7jyI0DNNo2O4Rb6YFqxP4IdGJCGNHKaFoxiRwN4knFs/oIgL2DCz7jN8fRHFq9NykF/gt8fVcEoXic99Ne+JzTMSnpAe8EchvW4n4CPQYdPxANtzsBzZJY0LslYD0SZiehc+GmxgrZ2c6cdQHFkhxaIO3P4XDic7hsD/YwsbhQNwCBgr7fbzX7zMA/A5/jivI7sfeup+K28d6hDdP2v5gy44Gqd8HIovnQXLeQQq6cdXoA6/QZzAIbe2IOzMzy6dOGUsUScucdQcDszJz4uSpvzl7Bu7is1nDJOGGH0chztXE724CeyGhH/1wMISPM8eWz6w4J45DH3OfjWXOnD5x/OkV54fLq08eX4YODbs+c+r0M6dWTjt/7ZxegTsxsdtRfwA0t2JzvdmoPb7WrMM/hwC3mRmPdGCx3LmFIw4ui4XkrizOGHDFBJg8FGtvs1YWnRttZQPHe05rC5jFqlTsHtn0/C5JUkvARTZxLsSwsWiHKqzlVhC5HoevQaKNnJRsphZ9hBf2tj1Y4cTi/aqGD1s6TJfmqrDfk2FMHBcWwF96yg0SAhskCKILTuiG7EbFeNQw/yE0qxIkbL3Ig42/ZA7TTu0ofyLQxSGcxOvoNOhHQQI0DEBKWcgj9pnjq1FwZjgYBD6JLdjprHUVqNWPNsj3Ez52hXb3O0YYpQwKSEk33LKAExPjZASbEeUmfAvpYz4epbvrJ8Q4Q2XHyqafWh1gDCoYjDPHn1o0LuKIl8yKvkgIgk9j3YG2Q2IhNTlUegOm0YEppvSBncAEUssEJmjW12yYhz+wKhmQrNMhwzpsN44exqmY634Qtd0gin1iIuIIySAwXWQ7QUbPB5ETu4G1CevliYkNYPhwYLuJG8fulrVZacKzNfqoVYdnA0DDqMGfBr/ZoDfnsjfn6M15dnNOawn/zCJ82KNu0LXDKO5brQabzwY+r0MXeO5FqdWqV6F9BabWatAGF7DBnNZgLteAU4SRD2cRt1M3nLN4e/jTjqMkgRGrxgbwwgX4nz/bwG8VQRs37IL9dM5tRy1QMZxCVaO31CC1I5xSm3lK0bvn2N3nCAwEkmidiAfIRT4uBkBSPIR31/FuDEMSa15jL7xcgLYJYmGwZVUyD1rjHrhNv2qsrxmPLhm9bA/+oJZ/4JEgxXEkP7iMH4DO8laL3cr0O8cBMiooSoPGtihMRtx2lPCvFVh6aw5Wq5fh33Oc5qDnzlE95wBR2gSJTj/o3InULV0bTvxzcvMgIsO+dQ6GO6c2OTT4KwPWsDE3YRubfhDUACNQI560cX7Ax8tuZ239Ka5INBxSG53fn4Wxq3Ku7Z4PZAWLxUFd5nRJBLoi3rJQ6wag1VGCgk3jBlW0eNyATx+5xU2jPtvTrKn9NEmX4R7IdjUnmCq2w2fH6FBn3a5VMZaWqAK1+b2tAbGPff+E8zcnz5xaOXbiqRMrx7Psh5aKHw6JguuhlG1uIuAT3iaARJQ2ER8x3knid3stoJpVWdPxCUhoUbb6yyXj8Jhh5F2k0UYEoim/H2DDV4121fCQ/5VokmuZEwBczHiEiwNcqKaLnA2A2J82/lmjW1/DFgfnS4DyBb+yhTD+asmoZ5EqMlAKi+myrYOT6/jdYUyNUCDUBtikxJttR0HgDhLimUo8tCKwCHNL+yTcyy8ttsNnZ8C8IBEsAuou6NfMoEVXGruzZvaZsyunV55ZqR6g0Y8O0ujYiTMHaXb29PJJreHaPhyW0L5ClWdnytm8kmcr1ody1tx+S8MM+holNR8rcNvrieYwIScnZiXP9Kw1qL+qXIAnSdcPESu6F9T9ldDT7vKOjbXMfhCiUYhYueFxk1SYDMk0oPwnHh+EC1dmf2QIySIZTxmTJGDSFjhx2A8Tqx+BmE6qypdzlNxFzzL2u4iBcP5OHAdfL0F3i0pJ6qpIRy9pgxPUBhMQdwBSJbHRS0FQ6OMAOVfO2jBQQixudoNVnYBrWZuz6/Bf1OmAw8HXYMAGXAKDyu4SlM8wi0WwVHDPDJDxESY+iiPQ5BUbbNTYMhmeZuUSBUJRAxjUWkULMrG0oQXitfN9G1uY3Gimli5nOPDMuj46g0voFFtq28bRBbprEYZaEyChmxuPURi1IHRpmkk0BNUAVDbX0ALmA5eMTDcKJyYbnPYXnGGuNRuL82uqLSIFJGA2K6DRNNlCoSuTQGtOmrNMtcGdLCf5HToGQoCedDPwEVCBcESyXXT62K7n8c46K5lrGVO7gSyMmzfLbnh3Dk1wuq8Bi+xjusdLekEHBFrsgPAEYpNUvtgNivsZg8eEApZrLzmck4EJErUlOMvyPYViY03yycCn0j2DoMKJMLcaDWcKrQnNlcBYJ1sU2rqyGHkH203BKWghXTV/0u4MgwBc/nbPWs/qYZwOQttPepRQpIcefARWYQxPgi1wZjy/47tIl0hIh3XKeRnxyYQ0jlkxvpvX/XxiSYTCiTaq4r2lwO23PNdYX4Sppha4w4ugo5uLh9cyXA4tkRQH653XPHSJbHD+SehZBXa+mOXeRVy+qmEyag9TAndgpCoGA6jgdtZ/4IB3h7e5YycWCGUWNK1wSSSujCHJsamKqQiGE9KaOd40wGTJttSsrhqaG4wBmm9buNKgz2ThSiOLFKsqd0eh33PgqWZR1VaA8zh7nhcU4OeS1CpZraZG/rWs8dExL/I238kuyHdQuDKDkKJWWbQbR7qXQMHCQ3LoUK0BH9FhPhcNA6IFISqSorYeG9FiE6EPH0nWI1DBEr5yMWkN/cDjayeUbILMxBZCqdgVGuJcr0UhbC49xKlFK9GI1KODbvv8EPajp3YgHUKqWxbarAp1JIOJDnugI8TmIeEASxCdJVgghC7twfhrH6ZBFojAAD7QQJxU+/NhG/k/ROXZoWA6VD7QuWLnp7AF2JAolfwEqeiCyWd1gEB9+xSJfVjbNleMtK3wHUOPbDJcFcv7ynGnI+MAJ4d9oVctXeQozwW8YtizIEvBy1tHf1V05f1OyVi65Vd0BQBt++BbWwoUGJeWRz/CDVc3jBm6uI+AB91hQCVQFbRRRQg8XxkwX9NWQH22ZJRpetkkCrCJYKmsSgvJBa7skAuyz6jVgcCHg4BkLZG8XS6migyE5KHNqgxCc3Gx1lir0Hln9AaKEZwx4Mf1Z8EEQj1ZrlCxQ6Vo/xRcGbxEcEXoBJg0xZTCwGiBeICYqAd5ZNyWCKLw+MXhA46fDDsdHyNVCBfVYObpgDI8JWIqMTAHfBv46ZYJspOByOFE+Zcaqbi+sife1foUu8j4jAKQDXGi52NhrsIe+CBXGkfrNKLpkS4IYhrM1IZWIc0Mzf0NH9SoHEqi58OTjkIPdHfDzM2LrrAy23SeKQbvxOXijsQtiXtS7O+vsrm1lS4aIniFaHmzdSl9jqkk5JFBz6bs5PihgxkUmgizY9cDLYLcRmkneKg+EdR6GSSpJx1ABrUrGc/DsHp8JfiARwvjlewiuQg5OaWRCK1J2oR6A40ijKIx24mj50jIrY4alXdKzGGgH3c7zPD8kIDq1dUt+g0G8gxKO/DSZvEznWAWLRTOiBOwcDZi9W3wBmuZlLUs8lB1/JiPcnkkVwY225h1HW+qMmUK1o2zunJ22Tm2fOz7K0wvyjjueBND2jpPxSTpcViYtgXedgOe9kVON9puECxmrSejP0xZzlUknlneAJmPms6Yte65sczoGlELQ8rGBZiax3O5NeCrYIsRQkUl0OeFBeaBNG1mB3ToE8Ydk314DWwTOmDoHIGybEI/cNBsxHsFqMpc97NZQNGL7oQ8+KbJqOCwHrrqLu4QlWWmw9NsIs/SJ7kUVt/++35whi8YiW21egqhDAGqBdQ4qxBcOlhRC3UXtAU+jTCXD7vPCfucWfgzZP9T4qmltxNMHLphxHYFwzdBZgF6CgBdjCPiaF2M0GEZwtLZeAhWmLQL6Xce7WF1CkKHUFgI4RSQKUT3gkEAQ3SSmEyUnJTmFpY88JwJhqO1yCcfgtuobnIS0+YMpwOOAkxTSorMArKp8eyKyEYOeluJD3vOoU99ouKBcXQhKfFVeDNaHLJB4i3c9xu+Bwx0zAUXNkG/RUYfsXIh9TcIBgqJCxoWgH4nAV3T7kVxzldJlJEdDdPBMM1GUXi0DbFS/JxQUzQfVdNDENru5sNk9Qa/Kfbl/l6bZmunYJyAvYkWB2yOvyVxQNIT8q4FPlG9IZh0AD5jgvpFT6dxDmX9j7Evlo5RVRuFuSpAT6AG9WnE5ye3ToJWsExZvaIbN7AKuVQKpT0MWdyEkjcpQVlDR+24ZTDC0TSrV/LKTm6aZkEtTRhlU0EDY4LjJfNKFIfM4BnYWjwIXYwgN0sUZXzEwn1FUuWvUIYTpofEkM0rm3ZnTUUundYdST6RYQ/kUr5neNx7v322f8RGL52SO+OCD6pD1OzYZwlWw7jx1nEaqoviLWuAZSibSwwqqw+siRxqzaxgjQx2z2amqW+lnFw0vPjU8tE04eeI1He2bbFpk4Je44Uw+mOuBCcFvGiMBbFFxjF5kRe4gBkyiSvp+Z30AIRnMZsMoorQgiNo7rDFXEjMIPIwFx2jSpe4wj1NMAZjny+RcnkHNkj59rrV1GA319ea8Vq+EiBDP9j/7qafLDWyXmycbU6ZjbVY0zm1RUMNAiHOsR0/5YVSTr9viYdV3vh8v2oErtDArqsYrdXKiuPlqrFSNZ4VlCgC0hjlAqaGcS14EUhyPk4tbs3TXuj84fdnNZZxXUH8ZXjKQKinrZZ4aj0LS7NSybXhPAkioA3CJ0QB5LrsUav4qNXivYZd9nCDL5dbVfgCWVh2jmwBMCy3GpBmY00sfOrGIJNZ99hptqpqT+iNGQF9bKhq1iwYuMohYDZxCFpiyarN1avGXB1LD6NgiVYv4HJuOhgCW1qo1zOJFaziTIZtoGYyyd6jwEFZr64abGyDl9IxC9zj6hKoA8q9mwty4hhYnkFNI527+8QNrRxRm9YKGLHLxvdYN1ilZ4GAh4w5yj/APMsa/2R5lfLPWkXYMIxzmU0PxgSGvmA1qkZJp0xl3FfBcxXw9Io4rh4MR7weRaRUDYgHH73sDJh36WJ9iUNrOinNy6wMKpwERzge6WI2GcwrVfWG/CPq4ZTuQFuwjZahqbsR0AZMAqG0v5k/wx2sA1tKPImOgSa/okVPs4lMhhlmjx05wER/o/BQPWIApNJmFBc21jBJo74e51XsYdbthUPrTjKI/bB7yEp7QKcaW4HaEXvu6Hzj6MJ8/bHGY48vHD1yCHgLTLxMq0fn7cbhxsLjc0cW5heOPv7Y4/OV2ULHSuUf58yMbc4RxPTp00HUcgPp5VumQMesqnDX5B4MFWhfL23Pp24dkrVTGtGxASOK7MOrY5TJ5KA+/VoGLzfHNABZi7eaH+WrG7waAFqJ8E3QVAAkmopS1fxQXx3X0BHBbti0tIBq2OeFLkyf6IY7ho0aZF5+FzWI1EqlkgGMpHRrQJaozNPMfyZBYtdjPUCUzMEXS0kW1RZVCxbjQUusf5X3SRznb+E+dmJUJcoUacwVMq2KktSLL+Xr9cpBO0nWVpPap68MG2yOixXIufftH2LpLPPuV3m9eGyLynFLh42ba6FqgAbORaAzy1IaqJfo6UEJiacWh9AvW2+TjQ8U25YEDOSks821yje8UEOlUSos5S1Rjul0gJXH5D3GUJt2sTHSB2aPxTm9asxX9lsGvHLhmyK59o3h6JfKPHxboRz96kxccDmbA0Z3SgHgdfCwTymIIt7FOyJGBNadXLhaI8ci8GAYoCrNHqsoIl7ko2qhzaY+TvExOKlsiQtPYKa9yFsyf1h78qmnz9SeNItN0KbF/XTRBKGG5rK5aMzDdq0aZielxRpoTh+Br1359XH4Bq3bETZeqF+q5jZLBndqACEx7M0yPs80dqqUT/KREK7j8tkyEMBVw2EZ0kJddEk5tia18+WvtMqeAeRupA2trRwfM/HO+loW0xExIVoF4qaoPqxpFime3mgcRSvD+B/G/BH4AI/ZjQx4nsWEUVj1ol1foLkmiTe9uVCULy2wPdczd9eNQ6AG61rgABOB+xQ0dUx+fEqc3aKJhghNwotgrV763kU1p0vj/J/8RL6L5hhWn8lZfNdYsPetzKRHglgVMDsKxgoXWJKDlaOycySapyBOf8mgqobSuHJykA1anI2l92Wdq6PH0E3MkmssyMXAJndTc5E1LarGubdgsmX1ZM5K4n5QHyZmSVeGuh7yTJY4tWjSGI/NHjOD+RHjbA8rzjCGJdyPzLlD48zy6ooqZNEraWiVqpusY1hokHBw7JhisPWEkc+C/ODMMyepowT84mKekJbmhISg60yjQDKLyGGlWA4H87/Q89s9Wj+I2cT+YIhAe0B5g55eowf72OlI5iXBLkqjKFjHM5gM0t8RPRHJepC4Jlw7PYEpMYyGcUKCDTwVWCSqDA/21z38nIkJ1o+IqCDrVBP2qTyb1+nYHENx2I6qsqfYocdVjta4PjaeM0zEt0SAUCpjud/CMpMoSM6yNn8XY2QnVuL39PG/9tNxD/n906TrA8G25IkxxszsJhAi18xqlgDFmu1x2FgizEN3LNuwSxoh6EmziTFccfwN3A1YNr/tyJI23XT55uXKCfe4C6XG+ZJlFctLWIFqkilyiL1vFGVgbIgABIfYVEbRU50WBV41elteHHUJSCLYMA7ZHARYfcItO0YujFbREzkOK6fnx/f0MWy2I5wBuEFY/9fuoUDPpchNt99otdvoPbCFdQR3LIkPeOqYOHhuA/Qm2FJLTQSuvsPU1NwUBjJgoVjDbsOypMRhR1tFPjyrtgF0GjlpNIiCCI1QEJ0UbybKJYkpEmsTsC7BSJMQMqUm1roHujeADcTKdXHZNbQDt0UCNbZVQJIeRvQxPWXlT+jIMZt8iLXSfNBFXs+1yA56YH0s2F35klub1twmfT9eT+h39vFSARwvBq6yklVeREunJtDMWiMac7Iw2MUclwBywALDMIVhcfrCqMs24yzmYDVwk5lObRbdavMDo3aOG8Hy6oKpPvRIroA1U3e3qNEx12yM/l402GaiR74Eq4JL87TukPFEG6wlJXrO2s6VCyziWEJ11YAhoguahX0px/cHKV7ItdZPE+8fx6sWTgVXMmtYqHZA90QrldAGVh0nRDw15LQTzjiSOt4sTi5zPfMIWIOGDFTwEzZoZkahrvAzp2S4pv7m8p4fSHCY2J+eUCk5oaKRaJ9DKpkzGup4ggag0lzkh51ldjJzQOhAh6t4AFCdFtGzfjySSWvZ9fBCs93MnzlYUyKH916TLDlnG6ejCwn1tfR3aNR0s5i/N2N/PsUcY2k9Ro63sJ3IzF08dIhmMUxa6IlyRUA28UBFsbxgsSTpDwrnEs/bZdIveHB5UvKddjmParmpyhqaJg9JCPpVVD5Vs4laYlfikPSOK+6obCqj8jxQmcA6ifdRxAjnHMu9C7KCHU9qq6sqgcXfJYLPeDqOQ4OLJ+XADdqgL7DARtQPw4OK8Ixqdea+WnLNEthu/KgFW64eiHnAgNVnagsn7vNzMvK+p6fwJWNWSmCJxfX4IfRKCVzRRn/1RbY066IpdGz9EiMlPflLo2HoallePuooqi9UEpC2qBr6IFW+dFW+YDRHp+B3sSAW6FeEzucvznTz5/JxdwJ5xH7IJwuLiOSiA3heR088Zp528SA/OBBYFb1qn4U2MSpxlBMMcsFlZ40zbxs5ZKBq6yoCYG1lCxPb3rqGDV2UJl8R+gaBhnxWvvhyR3nr2bxDpdBxEkdwJy2ZEFBULKFMEE99xCChWFV1d0KAUFBgSXxQj3javYl5d5tm3u16ZQ0TumLBVduy+GJjYWJ4sTF3STin+K84/1AFBytBCmQLMwTbtCT7ZDl90taUq6PGKK7RQXesKPARsLjqo+GrKnvf0YEnIGOD++AtwR8UbQp4RvJLps4yOxaDwnqXNmOPWLMVrpn1rmCCrBjfBeaoT6qyUOqAwwUV3CbE4/KcVaUjCxqtoYdJLam2D4MlyUQ6F/3qDVNUlWMoyAUDikeTkQuZyJ9UOMXfbMSA5arK3NSl+8sRQY1SQHJJyiNKtOrflLDUEMrIBbXvaEhnT1RRO0Fo900hQ3MsxFiqki1Voy4rTNTZoEq3+DoEyxRv1zKrZUI85wxZahamnHahjdgNpjjhOPZFB2VzL8ZmwMh2TFpBArOh30TlrJOzWIBuxXQLgS6cdN+TpMi04iYnONLuBnnO4gwh/Qudm8LBczCtQ4fKMOcLKuGoKB4DKPm+xvmeQZPNlBnM9hSf1hIv5Zft2C7kjfipXu2xwmiJbmCaf17JygtNX9AFFYYDDDmHY84tlSfumsrEYMM3fSxPla9poLqhRLvnTwauaMevNWRAXrlBurUvFnzOOPih7KttytBiRUuVgyLB0nMHJ0mB4b4mjQpwHjW+3jxL40CZeY+J+lQyAeJHjAW03wvpIfpSFvFOvtncW/1E7mZWnWSlwlJ4ShyclG8svUSN8Bq1EWpH4J95+L8xV1f+1ERB9hWE2H4CbKzw0gSXUAVZNpgU3s676UyQgVOuEM80oSf4ylUWJ8BEVWNJQSlVjVrxXLFsqZ+K1z6HB/CSrmj50UD6SioKna1xMfSwyQoZysr+Cm3xytTR8fdKUuVIh8qX6Oc9ZRbnKwAubhfZUVhQuSw0Z+ImD47ldFM2gahbUfJJub4RL7JUW01qG/5IbswjNn27Bt1e4nwIjR7pr5uRkWq29cQwvL1ZQabxY4u+xNSJ1rU8CwZnO247dVip+wEiG/twy0HqIieYYQqECKjm5gKfOyZNWNuZ/fZfElfNUqf0VRn4moy0B65NR6A4q7Cr4qsIQ4zk84d4R4aXx0VnL2k7uGSRbJhXBo2sWrpYYHKBYY7gxWoRiSxr6KiMSFnj0nmUL222d66iZALC6iWiMpbMYrATcFemlewzEXvT/LrY7WfkFVCTHRze4auStXzEr03e8Wbv+DmUWcNfdRpjxx0/k7WsufKYbawSjEAmenmBrCxgcV587bCBry3AoOP5oRumIJNlaQDvnnG//jvZHiSOozh7fAYvZk2iMfgotyjxs/J22NtBpW5Es7EY7S0ocM1kzJ2kUcTXqNakhForpg2FInII0DtwVpdX1GuBpFFLDx80xQdaS8QtdmpDsImv5R3SPOzTq2fKgNMzKoVB8P2wpGwMbRAegFVZK3129P3GLCnLX3qsOmYyKDRNq3/X2nFOwVzp/ls0kwhu59M0JTtOfzNTe8KbgmjjwkubSpIquc1YYBo936J4RZsv5Ww1BE8Qb7B12MDetIXehb4FnQefoEsmqK1aZRwRZ/9h+A7UB5LL7MCu9nFNcnUS0Td7398TRtbQ75giPbZ0UXy69IRMlPEgV5ykMJBK4RtRjO+Gp6cbsWooC9NkHTpghhVfQJZ39dj6aa+65sJ4vI5VW6GQSc1aJJmXczKDHDXMGvV7xsLPpQGoQVmeut4PU3k4A9SAgwf3aeRT7Sr69mtbRpLSiKeWK5WsehpkPSa9lIJ1sONuELXoq1oy9ZAD208YiIpGa+1N76oOTH9Ca4AY7nh4nIT4LqaDix02X6lo9enrjB510gtujFIhJ6wHW2kP1wFtZ3uD0FQzfxkN1rfkxC+bhsOnAb1y9W2Ow0E4TknPPlZogDE+vhUlBqY+vcnQ6Lv0oR2I9vGNaBoFGjkOI7XjWPxeZUIvVhrlYDqEMGtHlcEZyfm+seG7YyvjckaQOeAHXxBM/mcVqoXfVcj3pgY0ZlPkQUWeEA2IC1s+ARWICSOLTko7QVnBZOvYNLf6qQiwg/RiFo1fWNKoKA9Po2Su6QEgWsUrflVCCrK83OTyKC+6RLnqAX8ig/4MBv9VC/4bGDmAenOOEyacjewvXdCf7+CO2hPyVyy8cdjR1LT8UQp8M9ABf9siB48K8LJiZvlTFqxkGc3Tg0tuKTOEwFZ3hOeYJCRJRAWcWmRpxQMDej7Tg2hGw6SoaBaGXkEzez4ICLdN0+8O1tWXmGB61b2U1M2sNSDNu3GTA8bGwykdLBCVkxDzVHdU8nQYpMnBZacGHtO+QzQAzGPPnPzbldNPrxzXtoaq1SjIz32sFDaOKISZaBnSpuqZCkjrThZ7l+dK3ixWRqVGa3EzL8QLZl+JscTb5Lt+dWOOdvvmplqWYcckMVAfqZIIlu0bF33PgRb7+0CgC5Z0iSM4duRM5zwaKjgQRtSGL45liiQqrULC2vouCYcomsSZGs/AJDx9RxTIQFeU1RiiAiAnl/jCJmi5jq3SMQbBUK+/ySmkEoi8aEf+vE9Z1oCW7pjjKKIrJCWikuIe5JEqHmjaJ8ZVGhs6eJhJDCZ5kQtJJS6byq/PMzAeVePx0jEpzfzc8MqHWUu3jDU2JkAjC2sFqNTjrwpbHlioT3nGyhXU5BaCToPzJidFjSVItBXiJz6ADN6wTYsBaVAmsyqSM0rr7J7AVyyrcyhgD9BgA4PcDly/T7wxpgvnrRI2GYbtHkY3PAdTNmULJ2M7kwUYqntHsVEJIBX5GSvD0LjIxS9K8GhOinhkF7VWxoCT++dNX/yhoLbb8ukpqgAkUVr0iWlLZvW1IzSis5af+FU0au4JadLDNzLzhS4RFdm1p8eLnqAd0bHEaDs93iOP/GDhh2SNEnA0O8RYRYnE1haFiPVRWPCPQPBon8uTnCk9leTjT76VQARiJpSPo2EKFhIwt4sdoBeYgq7Rcf1gCN25xQnItYkHN/aTbOPMHm7ICEOHfy3L1RSyEXnvjgd5x+Wasq0PGqKeGNcdM1QmxkbJMWbyYoJy+tkZS1uPOs9L+Ba2R4zdd26P7vwLmvU71z7a++y3o5sv7Lzx8cMrr+785Pbotavb9366/cW7O9d/9fA3N/buPv/lg6ujO2/u/PwTaLZ3+cW9D3755YNrMzOPPGLAvZ0/vDFTM7bv/3Tvzke791/cufZvOzdvbt/7aPTFi9uf3nj47v/c++Cfdm5c2fnfn+/+4qXRT2+PPviJ4Hk2KrR9ePna6Mqn2/cu795/CQb7j2u/mjO27/3GOHH8Py8/v3P3Jn6Gm4fxJgexbjx8/xNA48sHN2B+o7ufsCnhFP7lJRiJ+Sy7f7i/e//26PlfjF59Y/uzV6HXzjvXHr712ujf74yuvgJ9R5/fGl39ePf3n+++fydz5G/njZs7L93eufzB3p3P9+68v3v7fz188/98+eBtGGz7/r+Ofv/Rzke/HF19C7D9v/eXGoAIzu7er3ffuLH76RfQbeedy6OPbwIFtj95kxGV0QdF896Lnz28chNwQAQ++SPA27n1HoM3eu0GowrO6OUPYCFgwJ13frPz+iej6x+ySY1ufwpjjG7eYG3+8/IL2w/eHN34+eitD0c/fWV08/d7dz4effYGI8je3Ze2H3y898VH2/dh1a5Kk2b73k8evvUqqD4giEQaVnYGyyoY4N0XOIFhBXZ++z6DNHr3yujm3d3Xf4df7/87MsCNazAUGj+7b9/Zee/K6Fev7t65BVgBW7CZj9751PhxRpn9GIj4MpvTzrXLsPyCJXDl1o3R5QeA659+N1c31n8wiwfBAMXRKy8zdEYv/3H7s7d23vvZ7v1/hsVmNBq9/OHDFz/ER/d/zrn58mujj27tXX8BWfnG89v3Xh3dfBPRQsZljA1dYcoPr1xHDr53bfeDV/euvAAja9UbUjFpFRuAxuidD9l6AhuNPnpt+951oNno5i22bdimAsYHxFjZBlZtzNerWLNhIDvevLX76a933r298+7nowdvy20GXfbu3gXOQHZv/OljYP/R1Suj1362c/2N0We/G11/Gx8sAFVQvP/H8/f/9EnYp3/UVgCGohPeufYTWNLZldqPjNGV97Y/e4MtCUP74duvGKvLK7Oo3XC55exxPlf/bef6v45+dh3YnS3gzut/3H37OiDDpcLbwGV3gYthtR5evgysB4R8ePmF3dc/3Pv8E1gqQAMmA0sMYHHLvvzb0YPLunzAbU3XnS0VEvTXLwC3jq7eAkEAE8HVuvPL3Q8+3nnrDkAGVtn74m2xeLDue3c+nRHM9eHoFdjl/4wbkEKb5Vvp9m1gmdGdGztXYX1e58x58y7jTxiDUZ3RhrHPzv339/74Bwbu4a17D299iDQdXf3V6M4vvnzwC+npAiJsNrNsp6B8e+/K3gfPGz8e74H/GNEXL61Uwh/Fst33zMzZIXa7LMnOsi309zdpDf0c+8lGh6oUx8FTNtSRoMdRuYIA/2Mr8RN7sCV/vgGdYvHrk/JQ9BAdyf4gACON/uCP3zEcJ0TbzaFBacfBs9eOw4PQ7CD2zP/v36+dXt/sEmfmZynf2Envv2AM+ivPCwtjfv+5Xm80juR+/7kxXz8y/f3nP8f1yF/ODpN4tuWHsyTcwMBtbwZ/v7lGhuBS+gOC1vpM2zPwF29nWPpj3pCvWsj+bPhUGkyv6TW9ptf0ml7Ta3pNr+k1vabX9Jpe02t6Ta/pNb2m1/SaXtNrek2v6TW9ptf0ml7Ta3pNr+n1Z73+H1k+qUsAoAAA
