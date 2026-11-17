#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '2ed174e3a3e3e5a784b7e298586506499b4086389fb1c6939ae092d67b0ffb50'

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
# H4sICAAAAAAA/3NvbHV0aW9uLnRhcgDtPe1y28a197eeYgunE8AmKZKSnViu6nEc5SqTJvZETvNDVlGQAEXUIMBgAcmsq4fqK/TJ7vnYXSw+SEqOnGbmEjO2SHCxu+fs+T5nFzJLyiLO0n2ZJVfRYLn6n/u/hnA9OTykv3A1/n5xYP3G90ejg8PR/4jhJ5hL6yplEeQw/G8x1u/wevCH/VLm+5M43Y/SK7FcFfMsPdhzHOfVbBZP4yARUpGImGW5mAYy6g9HfTmP+otoOg/SWC760VUcRuk0Guzt/RhNs6sol6KYR2KZx2kRheLs9KSfR7Mox0ahiKhr+LwSRTBJIimCNKQHZFbm06ifxOm7KNzT3YocOs1DKWZ5tuB25XKZxNDVspwk8VTE6bIspHCDvIinSdTjBtEiSoueKKL3xV4SrKLcE0Eh8jIt4gW0gY5ScZ3HRcSzLeZ5FIlplhZ5MC1EGCUxQEITHIgT+AjIidNLbLsH3+JZHCFCUjGdR9N3IrgM4lQWFhwiljD1fghtr2Cuc4C/AoGn/GwvzbhXahuE3CBIV4C8rIimiL4kmwa4AgNclz1q4PuzsijzyPdFvFhmeQGPQE/UTO7t6Xv55TLIZaS/T+WV/vgPmaX6c24ayJXUH8s0nmZhFAZFwEOG0TReAD2o37/mrz3x46uffvjaP33xl2/8n15z02VQzJN4opu+hq97e3thNAMaSkIXF+RIyALWo/9n/Hu0J+AC4M6CRURtFJ5FdBUkZVAA5QW04rBSmcYudkOU80upIR8ggrCvPALspPBnIMuJmztv5SOnByP0bLgGaZYDCPE/I9f54ZvvXjpMK94gj5ZJMIW7b8vhMAjpSc8bIPETAJ6CJsmC0F8Gl5EkmHwisiOCl0AL42lxXpRAiecAZQ/WvLjoIcAXBuLvg6Uh23/ZVLucr2Q8BXyP+hMYF0gdxqFe8QNNtII2uBbHoprCACnJx+8u8E+G2Dx2ymLW/9Lx6AGa89GG+UF3H26oKXL9BCjwHfxK+IRlKACjf/vm27+cCEANDN4TsyS4lMfw8/fe+ehIgYdXERdJBL1RF/wwcDcgzDsfXphW8YwbDqI0lNdxMXedZbAEQJbhzPGq3vBSq38sHIU2x/wMHNvu6OTse+5GACTO96/gu4OwULt1XVcrYfcuG+3zIJaROFvJIlqcvAe0zJwynSaBlCgcQt3fLE4iGhEJVtHIBxr+Rq0HXvMYJNixSGIJ6I0GszgNQTTliOp+vy9ev/jfE+G+DR95IG+AqY8HD5/D/bcpLAEht7YIVbe4fnEPe8cpRGm5AJlWRC4O18As4AwmgD+cx+KRGF0MUDkWrofrQ3fEn0QSpfws4YO+0vBerSsisHOXEUCEhQ8NLvOsXLojz/MuNE2c430Y2fWO4P8Lm3upE2C1B6J/bxd09lppJdI9AoR9Kqd5vCQd556N+meH3v0OuffmxVd/OfHPXp+8PEPGEuKBGhy42Y3eL1nM59m1hIUKpHj5CtRQUi5SRqpzNnKOhPtFT3wTAM69nro7xrtPeuJNXlY3D7puHuLN0dDcvdl7+eL1m29f/YC0fmZoPchX4g1N7EN6cwSj5UEYgHo1ChsFMBLU8hThWM5vYKrjH1FxTQl9oDyBaFkS7/346mf/7NvvX4OYOEbJMc0WS+AEJGi3D4T8doDUDJLZNV8+A37Ax3764WX9GSaLxoMPz90L+B+F9GQEH9zzYf/p4OKR+/zo/CS66D/HZs+9cw9bKUnpuLfo4CMf+czZ05qB1K7P1o27VdpWyoJ+wE+Vhjh5z/YIUSYRCcgIEAxBkqwaFhEtoiVmmIOMmpgGROR+HnUgl0HtogUSOpuoAfA9KWdo3oXiX2VqPnvPHatrohnsC5ozNp97QD5v5fNuCno74KeZBxiVR00s1fWUkTekK1mbo9STYIVEIa/DAHC3APVjyT6QbkpS/6Eu+uviES3DOC2jSrQmYE4ef4RFMUSLQliyX62Mkf/VSlV6AEdry3XVsi7bdXcN+c4y51jMnLMPqomRyDdOrSnqUWoNRiX2bUmwep+diMFrkoUrHAtmfa4HYzGvZ7dFyRggKkVDKLio6ywlPUlw+tMMhrTmek5A1J8gDjoW5/W7iE40TBBYnHrNVGmDTE2P6Q/MH7SH67XaADyIPWzT7mAt3tSTDE33cwsYWUnJwSIopnMXx2hPQHW16O5F42IAljUuzIJpAVmj1b5t+jTnwoL+Hqej5wO0yYa7/j5W3x1lljfpFgkFO/KQmzV5tMfssN0+ELXcgBiphCkZ2x/w/xuQgUZXf9CfboyTy+r7Elb8g5mCbd+p6TFboTXIEu0OEzsiR/iKZCsJ/kWWo9sKLmgG5IiTbIzHYyguQFnpUKMjagvo03JmOYd7dZFAaEYg4BcGzWGahO/8geXuIgZrF7y1YyGjwrV4D5Qa3eI58Lxw+bl9BXcHvCoqgNzTgLiu6sCMVqJd9WoQrixI7kjp5KAEQeojLO4abUJ6GAXweV0Ff1XGCQcoxk/70IEdwaBeBboaNNcFePVo+ZcLKVzjI8+DZNYvl55RxSDzilL6k5WvhfIHgxBl7qHCHA2Gwj19mbw69BThELVJEQgEF76/LPMc6fSkmpH7R0+ZjyTVTsfkJKcZmpXQNF/BUjapzpEZtjgdP4JGS3SsgqRvQQnwYIQC0AisHT4Tc3Awwb5AP1MKcNSmOIdJWQj01zGgk1fRH9BOQceIw/5ISHBwIz09rTsDbQhcQaek2yThC7pCtjHhlYGj7FtGGlnDsFTK+ADsHSD2vjsdv26hT+EEYC1ThOPzbjR+ruCUzwwwbTgYZwruMFNUG0znYjQc/lGAL7cI4hRZZKoGKdNFFMgSZgk8pjCpcYgYxbZXGO1SNlF7TN1qSlEfMYkoOhPWuESZQgq5p+M+eRVXQR4HKcemFEwNPJID4fxUmXEGkx10uEPkekQeai5+MvgS6fDlq4N7w14NV22wPgn2Grhqj3pP2GO9kpVFZaWhHDOK00UB2SOO7xG99gjZlpUmQTdjQMzWfnXDOXzfE27ZE6VfplOAfoz/+PM0w3/42atb1djrOatE8NtGzbAUSnxwcJRZ0lT7XbZckRVBAs8oNeHOxx7Yv/rbNGubUHqQTgsK9JhLXQ5+KQOQnOCE6L6c4QBTKyNAMShzIDaMCNYCt55Fus1OuVfxECnJu6/O68DBamvD70OrqcNExKoSmIr+tnvEpXEoruzC+nYM6fzk/9U/Oz2BRmXnr7DmUV4AmxQrbEP00G53OvaVA46m0Li7Rb0rRVvtli9fWX0B5XW2qPfFtNnRklnY6s/pFidOx7NAWNaDSGbnw4s17eKZr2WCbjvqalvT5z5bPLQ+NdNHsWf9+ZuaFQfEcf9RwJNmcgksdpAvw8HgMdDxDOADK0bKCM3LrtwOZZXuN0yIRmoagTVrgiBH4ItmYD8uIinBYq+SJj9k2qlUXmb1yHrDWvGRMHk1TlzNgjgBD0k4IHzUQDqMNUHD11cY2h7H6q0L03Qa1mBlHmCEADMqKl5sQvo9ceBdeLrZaH2zkW4GXsHjZjMrlNMTj62WTza2fGK1HI83Nh2PsS01fsA5QkREOcXcXEhUBDZFAh5DvI6adCbTIqsB9UeUYI0W5CvC7uhopiJxdiAOtNpyfjyaZuNcx9KqUBrlOxBBFpeBEjXBI5dicyOPKGmGIhyN9qYX/FhpNZoYurhKv6I6vtCK0RPHx+ILUvdBkrhkhZwfXpDWzSu3t/FQY17KPFIuSyW8yHuxZ+GgvTJPsjyeBmB4uPNpkh32lnPwmzwCGmmsZzJFDMeBWJSA/RRzjeRbYVaYna1a39NsmWdhSbi8DmQ2geW7ikIy1QC25bxCcPR+Gi1BrsHIvWvM82ZpspqPp1mZhBPgniShYEE1JQverrmRu4PAw7iKvakLMoHUbGtzvUbHLASCsieNVkuRTaI4ZXOrQC91Oc/SAPpPwyAP56swzy6jNMLO4bmIHDLHnl0aApjTpAyjYg6SvIhlEi9AU4STFQ03Bg8QaI/QUERLDeJoLYgjG0RkAawOYEcQwNJznVImHsaVqGZsUCdl8m45Z9M3m4Ft3QPvBKaJy7dlyVECCXweR1LGM3SwDx3sN1d/OBgtlmD3SBmXC0CaXM7RCHw3Hy+JxA5sEiN6bzyiKJMeUmRZe2YbDRB9In6MI4aDlC2/TK1dsioiWYMAntU0mwTTdxlQyAxABtRmM/htmUeSv3CPSL0HNg5vRaPVBAUO0s9mfTOM4OFJ/zdnhvGzPEbhIq8BGvgCEmIRge04lcBYBwDrO/xrQ4czhOVaL9/GtjHmNOUXiPI6Yl9K9Mn2yTMTUx12WCyBAGUtFVGbfFsiH26QyDDfzTL5SU32HTZkMjy+RSo/qcsstvgqmYn2nhmJBlCenrL2GCWTWrSmawhlj7GpBH6ZmXTdXNemOtpSaIGCQPRlrCz3XmdTzI5jUy6I2Vd3qzlQ8r7xqC6O8OE3X4U0HzfaUNVMlmPXXVmtUa8WuRWj/hetUbICI1AwjCleot7Ag2i2PIUfQII0blvEiw+CfBDfK5XjVozcU8qnaZg7in0mCpXG9TcevKUaseaqlOIn8NgHomOGNitiWKITJSQgpZDRVZRWXYllRurY7QMAw/GXB+KvWIUD3x6Pvhw+FX/1OPzZCgjUro752wFGJY2Hg6dfPP7ysQiz6xQHwe9PH3MI0QQMnynLYMuAKgZaRRh06npUC9RQW8vFqjwVElT0QD1sA6Nb7VWsVaJeBrNAgM0j3P/8ezAYeGSwxKq+DW5vnrCeiw7TghsiM1EJSmBWkNnTWKqYaJkGV2C608wa8ZYWfCCTmYABOvh7WWDA3wlj6K/Q6OkzkNo7ICyb50BErDKs0rPLJZpENo0LTWEdXjyWaUVr2XFrucFoQ61Bh/dJo62RDVYDha+jWt634Yw2oCTfsBtEtC18EgbnwNBdTrElEvw4xG7OHZIITldrWhFoR1gbdYE5zfyKi3yiG581e+Eccb3IWmisj9uluDIBfGWJdqz+RnmuHr+tMD9YL8x/jGSZFLInTk9+BNGUgLZWKYMwltNSSq09R6KaK1sruLgtKfv7kvKXgYyyEkUWWfE2CC5GfFnMn47XdWMEPOZxjCdAfoQ2BlWwGWUVTKliI8FejPYveoI8GYGuDArtrdIWfB00JIy384wEkjYdwcbLcuPUgTehoCJv4u6S+ZcySEjaXFWmi1ljEl2NIXpU3yvn4MpjISBFdUHW3E4k2+IeJO9ljAqSgtJaQQBMKWBSj/lRAtgGIJiQcY72dEUCPTIFA6Hj9uKfUZ4JdDE+UhLfO5G0qWC7cD64hXA2AZ/fi2QGuVu59Z2Clpop6Wfowida9I3ivj8ZLeeA0Llf+S+fUjyP1ovnFxNJ9Wq9ml/ft/x6Q+XCleiKVX4+CAmV6CWD8pv4ciDGaPyx3/lrRfc5uLc9dKkubiPB2S10OX/nPRP6LqaT6z65+oUkvuWfu+ygbxH4dRZEXiZBr3LwxtQHk0zGxcrTGkBHMYAPZ/F7GO3Wlv+bOUWWmoOCWDNxIkY/9J6pfLsKFwkdLxImYKRS+FuUg6uWkqkzqqaP4RuKYiAeUTs+s2PsWmcUcwqfguSzxf6WMWfxJchI26HHMSoTPowvY8xjUf5VoVneWv9w76o0355VRejP1o2inR3QH1GeY1X6rZTQJMi5sKIy+3U9RD2IfEvlE5TFHLf0VOynOW1UMSI5Frx6z7CpBA8x0hSCBR+dqeCu6SuNS2Wr2PsEnE3a+VIFEHnzTZZ8nDZznZ+x1l5tJeogcfAnJ1E3lQfiTNP4qabxTVA5Jw0GQNrSgVIsySoEFtxLoYKlYrJSsxrb8GLEtEVyFVBrxK3V4NNoyDVykprdWubyymW2RjoStt3mV6zS9ajhHB87Ufz5KTQnC+zfSHPexrHhCfV1gNb2a9jswjDtr1OFB7fzYpS2c7VOM+rHVnmWk+PB5DNmqo45thVft5JjxkSOwg9YCKIizGuh79JxTccjoAC1yGbCClDP1D5Fhels1hpK68At2gYFTJ+YHURaH/laLGNKAwr37Fu9z/GMC37ODlgPKeVEovx0vG8nu+Kuup76kNr/WJcfsEPn3kc5VhVLVJVHKkikAlvTIM9XWDVEZZHuf/7tWaGx7TDouaAisZ3FSktztYmaj2IMQBJ6TWE808EpgLC4k9b7XIo5LgCpN42xfQt5wWUeKVesqfU6ihm7YAJ3sI97OOEPBc0oRaIIhAT/x2o5RJRx0z6Opo2bJiNQdMHmZXIC3KMKzzPGcC+mqIATBjgietaxBk6ciYnYkaO6Vdn91u7gwe3dQRaHWOD13SbHsK1Q6oovWWEFzzxIL8F33DI0dpJJ8r19jMsWqFDuT/dx1utjdd/dkzTj8Xr9Vw8L/wArLr4U+6J++xu26sfjX6kA0fHYqAA5OUgylT1BW5wat3CrisPnT8drNB0KyGbihhjspXzEIz9SeUl5t3yOwZISAwXtKdw6FxNXuk0+pzXHOoZY2GDpK4gXGOoqkip8hapYaxMdhiOt8nHOVytxS36X7rgzUWMVp89u7X6BKJORgqTmeHHO4Hbap1nuY3mnIKc1Hkm/SYKD7YrgGgU81tN9fNqFrSIr7y4w8S5M5h1h2kz01ZJ2JmG2SvYm81stPlkaZo0X0yXdGXiS7vShU7oHShLrR+hYge8edTauhIFq/cpXvKf9GXz4dNy626yG/AjBbiWFanWYn1i+P7mteOes32GVhFdlCSyj9s0O6Jbgu2853xXsu10ifku1vsB9S1aJv5Y+md4Ddna41Y1R7bQ9jCJHdb528DWjXs8zkF5opG8R6yo25UaDywG4eY8Pnn75VDxCh+/xaIwVlsPBk6ej0aGnt2jg1iCw+kbDIQa08NOz2uEv28oCeMeBihRbVDDsj9RNNaVqjwbWoYCLlJDQghGDxt6hrakqs7WokTcXQZKlt9dD6PdQyrXL82lqGbMmPaHdndZuiNtpIiz1UZ1y/BAsceA/hh3IC0+PURu2SOG2woW/okZALZBdJLBm1xZvOJGUSCqifIEbx+6xYOBwa8EAKqqPLxl48rvWVes1VK1koClhqIVaSp+X8o77BFgxVCR794Bc7YgPVVF2/+X9P4CDyv7SLA4mcRKT/UfRZRBuZp8mGLppJCXuT73/Wn6untejuuaUBy5/54WfYzGdibcyapAlsOBlCJ76w4cYfaOW56ML0dePnQ9VjfoD8TIrU2SwLIwS8eKIs21hhJtpcFE7Qs49jocfi3fCpRQyrEGUe1x3/s4PqMRvNBjSd+SdK0Cfuo3p06h/0BP09wlPmcZWDayNrOaEMJ8OxSHleepbk/OriVnU5nBkwadZwUNDO1hJkTZEKialsMaF5mv9jiYH2CTchZ48tLPhsJqbExtCH3sm9mIUPAS9AujHVeCgBxbGWp0o7rvpWoavYBnIbafyBIqTEDTCxSSXuB7kg2KAIcmMEyLLOAXx2FNdVTvz9MN63Gcmc8bxA2l0CfVk2oFy5g3Uek2X06joWlR1n1f1SdeqqhZbllUBy2tGz/joRPoMmN+9KOuXfLRlyXGAu6x5o333ohOkatVHnauOLWrLjk14xXFjomGDnoU7a5+gETuAcGpw3gDtQg+vfq1h5aIljvUMaJLqkW5UXNTO2gIDgXZmuMFEulPcp++JPwFxRP3RGGawCN4jmfYE/ex5Hh/91xPk9/4zXhr52dOjthB64XlbzsrCiqGKYaoOSDbhSM2467uHwd8YE14NGJykmg9IRYDGfBtdeOLPa8CqnrjjTDVnYWKBEoyRqgLqV5nFZVBA+7R+GIHFQSAFLSbi3qP3wWJJarTh2SkFonQ6lkxgRqxKnvnFdebT3FrO0ny1xNAtBQ3BDyzAz0P+wVOg1rsefrFaRs1cHYdcfKzzaQ5SWTBKN3X+XidIn5QcPEJ/m1ahhW5izU6+ahZxpDrM8RVmoGzIhcG1bCwamzOfy1oGv7aSlKWixRTrHQtHbWPhXDCIHSrM6rPEB/3bb+hf3h5lNIRq+PrlyRv+mZ01lujrhmwoBipzJlmrU82WEgmzEk1mPhtQvGkXWFD51rqRbNyoogqrmsetFTnoPC3XLqdRTIkDJSHBNo+LQp+ESVtmNuDTGoO8sorxyjT+pYxgxsrAY3hrGbh2Zv3GVjanI9+u1rsjC+LjuMD+lfRlOTF1hb5e0CaHsAPrg0fo23TZzYkfVzLm0IQow9IwmBhirZ9VC6XuN0iLxvj6mcN1XNdBVVQGsb4yUNcQEiVgSaXsKNscrKWRb5OkxFIzokscBfguFbCE0wJGJLMWmJcMXWY3PKeJfjOWGSxev6oK1a3XDeiCInki/lQXLVy+Cr8ceuTxW3KUDDs8vUsiRZaxnNtO+JbwiMOeEbGRKTL93Ibqc9pTWqs67awP7eKCm9r+XtyYKiXFhN3OnbpKga3d9ANmYLxQzMHMaRn2RHJMRJ0RyGp0fByVlKkOagcMdNxB7UkmX+I922/jngCv5LCpFqwdV0cWBOb3DWUI7ZI4bXy7mES9krw9SxUIGPmPZ23g5ESrSJsGVMlYk5+tsrJGwNVyhcrS10VNWsKaUVplkTQK7297tF9lZ6xUg8pCyFqCAatMclillJvr7g87u19XPwf8B7RDVEuMj9Poro4zahWwXPCKN+VmcylzxVZNgdPS3zXdAbyvUB6nklNdpDADKg6sm5gb0+ANR1rphJ45vJorC2RVBhYXz4x7RpWu1rTiLTl3Y6cYfc7avU9WQd+o/YYNUbNUNw7gbjQkvUrwKDllDg1oq2HDr1vKCCrcBfI2KpueqqvmOxrB69MltsgincEaveZwfUJBdVcp1bkS5DbmFGRln4lYri48jCxqm24bpNPazcaGz6k+ZtOALbG0mZu/Asnar3OuKmTRarklZq/JopiBOZFd62PTWf+z9t9IjHZQhgPyoMYjBAVPVaU+pXUWu7YYmMvUqeRswgSbDfXacBXbsqluhcJgWKrUIQXzjMVRTcryEhecwwV7ON1cd+vQDkEdAo1CtZnQYIchUSkCi5D/KxxoLOqXr/yu7Sxt1tMmzh34Djz/5jk1W/lOl+6JbadSmB1MhgFahf/UoV3lRiXW8rYWslW53tg8pUcc3Y3lXqjOOwru1e4jqkkwk8HM1br9R89Mqebm6jinOffbm+WxbBnXm+m/ZXkTO9OU3a0uXKUAyZXf5Bgo3KrT0VpG+S0Z6i5Opcmk3Hva5GvrpRefICNSBb0W4bpDOHsmT8M/1V8SoZMjus35xljaxfmm6BPHROmM39qRBs4D8b3ukclUrj2H1Np1YQUY7M8PHoifaT+AVV/lWpQsvXVP9oVVOUynf3PVcON1Kq3TAHQWVHsr1imivVq1sD2Y6ND26vBMsS/U2Y8kh2oHGvbMjvAJPAcYmgBQC3Ry/26VoNAhqYOpvPr7oA7gm7Y4pKjBho2J8GtEBy1p8NSOxLXbEetQ2vJV2+5BYbaM3NoVrHZHWY4fb5TxOoC8ZdGIFDAc13C06h84KsgnP9JBgPYpj3Ug8cjH25y5aITcprNXcQw617F20kB9QH0i6xYe0IaVa2oNeJa8ajEeKpMtNzHEm3nTv1smtBuuw8GDqT9sOHgPm9nQLkfEGnGGoFHC9HoeT+fkq1ae3ufW3qmB+LaoXKOHxqB6CFAdGVKtwgZCLgMsRWwMxg25atwYiyzzQBePhn9z4dk+7irElBz9cDR4cnnTE6uoqPlryibAzYHS+OL1RVvjmMNARtWnK1a+RIINsn5hR7ktnBppDIaJSjP3bEsXB2jYw14Vl1dvjuLgQK/Bu2BfAMESmlvhc4U1YPllQnupG4H0rQFzfK1KvSIbhrRD54gKDGfTidvqIbWytai6EvPSxL8buVlgtlr0pD6idrEMbwZL3DOJWSU7kdww70GuFddYzM9lqmCLW1mPLnl0m3ji0UbbtPbOrso8beCvGc598atitNw0bxBy0y4EPy4GikWcUbQ1loodNgmor634F55yq4tFjHpo1u4absem4IWvl1pf26GyhoqRHVt4OalbiAQIqaC1rB9a1mMVVKs3a7BKkVFUTTQyKfZ2GopOA5sEIXJkzYtvcbqxXNCswKOo1GvJ2mzlMsf0mWM4EEUy2ipjEtauBg+m2tAlEe6JKpi3MCZg+av8erGNkTBu2YJA7WftOHtCO1mAMlJ8eaFUYsUIusxwok/hsgITzZHStsJ1AWv/yGj3TFwgwOqcZNR7SqJY4Z3aqetcRwjox6ObZ2WyloJfJIk2FKhMTWfZ8sYrjrAAtYfLWEtjmDqoZki0VyN9e0BttiHjVoVwXHwfXVuF5jjY19+8ETDOtEwCbVbEyF8U4dQw1SrDnLepM0Ck0dskJJ6MjLdU4gJLCzlXAd2wZ0Cv3MlB2+i33g1e5JclTuA1/eJ6VrNBEIZ+oH53nX4fhKzTw/PtgzIpjp19/K7PH71E90A9xy/2wXuqP2gIv+Ir31y8i6cYq3cd8DsJj6nFvi6tZh9SHdrqqjb71RHH1TvciveF4w1iSbXZ9jtIOl6YoPqpDorj0zs+8P0bfX4bHWGKry2p3lu3dQb0oHJCjjvea6RKHPilKq1XLLQOjus4UVafGss9Gbl73Kqf079z0LNoFJvdqjBcpdXopRb8yfqNI1JWNoxKGloZslodUdooMjTTdY4MKPUyJ7CsA55bIyCm3hPpo4yjIs8NG43vVKnfuhoPN5a8GTXiilJaKpx0cSQ6j8LVp62Dz00ltBfeBdsIzfsb50abWqtzYtvlozdMUa7iKvt4NN+ijQG+4BL4h97vya9CxDuDsFwssfrHNGTTNC2Ox1rE9ET3SxNJ55pxO5xbGC4DG9d1rqEPkIEouI6drv7Q78Ai68B6GQ7NFOUX9DT4Gqygn+mGy+16oDqiJMSzK+UxvyMQuOx8eDF4F63wnT09CmRwoTVuuTh23uZvU6tUivtnhLCz6Xb/SOxLr6+pYboKsnBIZLAI6/jtCO5UsRyvC6uKocPID+O8kpR4x6n9Nli8g/9dSi762btjeo0dz848TiKMX2Js5jXBfUsuCWef5Kjve/xyTP5FvT2IVC+I0Wt85Wrtxa+oqz/AtG6O7Lf6qJe+8Gtx+D4LE/ip+dLaeg3YEPQXCH/fx4X0fTws2fF91Ga+r143JldyEKFYZx3n7X3K9//K+vuf5fwTjEFveX78eM37n4fDx8Nx6/3Pw8e79z//Flfj/c+TQM73Hoj2u5+rHMe2N0A/ELVXQDdildb7nre/3Rn6qr/fmUJF1QubO1/VzKb6Zy9evwZXhM05gdacN9iTUSH6UZmBA7GM8NT7PbAPPvsATY+OscmNszcN4Q7ccPbUq7DFvmy+Il2Qtajb/bdXcHftrt21u3bX7tpdu2t37a7dtbt21+7aXbtrd+2u3bW7dtfu2l27a3ftrt21u3bX7tpdu2t3/X++/g+a+89xAKAAAA==
