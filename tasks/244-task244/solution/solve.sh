#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '73cf178ee1a7fa2fc58f288788639d2a44c80cd2c978f5db542c382c75beedeb'

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
# H4sICAAAAAAA/3NvbHV0aW9uLnRhcgDtPG2P2zbS99m/gqccEDmR5Zdsto1ze0CabJ4UBzRBGrTAbbcqbdG2LrLkiNLuunv735+ZISlRsuy10+ZaHCxg17ZEcobDmeG8UTKNizxKk75M4yvhr9Z/+f2vAVynJyf0CVfj8+mT08ETc0/dHw6fPBn9hQ2+AC4bVyFzngH4/wasP+H14K/9Qmb9SZT0RXLFVut8kSZPOo7jvJ3NomnEYyY1i7BZmrEpl6I3GPWmC57NRU8kIpuve5mQqzSRwu90vimiOJQsXwj27LS3SqMkZ7qxacXmWRSyWZYuqdmqmMTRlH3gk1iwU5ZnPJHTLFohTK+TiWm6XBW5kExciWzNVmm8TtIlYqag90ORRVc8j64Eu47yBXslptGSxx7jUooljErodKZpBoPRTGIRzkWmWsu0yKaiF0fJRxGyacyjJXWUcimSXDKewF2FAn5J8iyNpdfB29dZlKvBoRWP1zKSLBOrNMt99iKO2SqD2VOvEvIVjwvowjNBQDJ43OFzHiUyp3FksVrFEfRRaLFc3OQs5mvAdiJgAQS2WlN/sYxy6O7jYnWImkEwK/IiE0HAoiWiAWglac4Rsux0zL1svuKZFOb3VF6Zr/+WaWK+Z2UDuZbma5FE0zQUIc+5AhkqWht4JenjdMpjpBbgr1queL6Io4lp+Q5+djqdUMyAr+LQxYZjJvOsy3r/wM9xh8GVCZhQAh++LCZu5vwkHzsec+DPQsVP0gygRr8K1/nu9T9fwlMcrksj1C8f1ifmU2j4UzEY8JAG69p3R6PhCO/2nG7XR3Yn9Loa10SI0IV5hRESdcwmaQqzXQK38Lmo8P8uTYSaQAR90pxVXUqkMh6BLHy/lrlYnt9EuevoNRdXUSgS+DJdiOlHNuMR8OuYOeyxAYTY/N/7b1+xM3ahSe7edElAb1iUMNfpnQxoEk/Ux0h9DOmD/sHX7mWn84C900z6/bebfOoxwaeLklMZCOAEuAkExGbZilP9zsu379+fv/zw7dvvvkfkaLK35ZSdCkIQhQ7Mac5lME1HgRLloHrueFUvLUcBIRWIH7DjwH/yxG6Ti2wZgPRKiU8zMRMZ0nD3wHw2g5swslwBFYUM0iwou+I4L9+O3Hm31iXOBA/XQZRM4wLYD74EIoZRshQYMjiHXrj4Vg9qKXHKsNXkBeFXJKAMcccNAxSOYJWluOiACBFT7oQIP0FOYRjXQfrDwnFSGqiJQANZq5intEJA5N5qAazMYD6snCC7XohEK6womTOnRV42L2eGwkbDE20jZJNJkVcKnE+KmKNiTJN4TQhUBGLnrozmS97dF1ql7gGMTBFnGDFjUc5grpo2wPMSyEewckQjZEmxnIgMqEEqEJTnvgBRowGVrf1Jrw0za9O1FkfdC1Dd5WlGa0IqXODm4emNg6jF414ocpBliQpBMHe1gA0DtCRoxrlgoyfdMXv4o2CzIqMJcr0R8GQ35o7icHvZ0xlD8WDiB8MBug08AA7wgKUf1mcRzZNgCRCBDZA9eYjz1X2VDFhsowdzteCTdEr2WIM00nLn7SX8i8+S/cGzLy/7b/63RP+NJfnPS2ENU+i7p2SgHOE8hCWEkp0PSqNGCyNu+7A9wFOSWNojaPr4sd4bXEWoP0YWuWTXAqw4+ESGs6RpL3kEWSMOOkDS3uwraITNAYIWR5+KKAyuYe2yQHwafqXE6T456wGkr3dIGtgnS6RaJTcgawkYCfJwWXvrxl9A2GB1A5KQKfJ7kKcBbQ+n+wrZ9yX/cHA9zj/5bPgVU3PMZUPAiLrW6ulFVbTfe7ujodxlAeRgPbYsgncDZIoz9v4DixP33RVf9d8N8IZaHWSESpxL6HtLGQ9likYdqpDUmo0ArIEX0AXSUkz6xawubr6oD8CTyJHV7xWLCqKxD0LbLDCmxCEC3RRakFmiW28vqt0jxW7b0ncfKp9RLTUMCgiCWIJRDl4XQygA4Yk/PH3GPr7jjOds9Oxr9s+dGgD8GnB5UToqNddkKiNo4PzmgBD6vrBY6YTUrMVkFfNtn5zTUCcVG+2vT6ZpuggW6zBL5yIJJuDboMxNInDB+D4bOMAcPd2uV0qe/I07+KOXb9+++dPv4LSl6g28RkVYfFmagbDeNJ3n5eaL3Y3cH25Mk7NII1pGNOGIpnVlNW+Yw/uC+g07dYtgv2CG3RiyW4NQdduXuAsY2rtHxBvkxckpgiDDZksRRrAwu7dvgwa6T24i5hSF6jK5iGalWtRENjytd/UDhS1MC9zASNQOMZSPYtYQM0XIHjFRNV+pfCZiG7D6MDqnGaMUk+f7cn7NtEYpAhGKMWBnW82KKbL02jKbeQYbTZT/Rkl5RRNkB01wt5xoBgbtVMznQuJONVnjXuPD9naAedsuCC3mLWF50HY0+rMLyOh/XD5Gzw/ZHIyIPKJ4FApBmLaKigp2b+xPX15EfN9nlgO4l5CM/MOEYfQ5snCpA9EqJqvXOjAhYwqjB5QvGFOIvRGNzvg1WKhlwF219JG8Af52YYw0BHTPnCKf9b52uiqGTlFv7dhWBEtnGPIRV3kKE1IP0xnIIsaXHAxDAzRPRWqRpDqOZO3VuOKztIBVgMZqJo4NEB3dxvCLUXNw5Zm/OXTsM2X3iitX2oa++OSDmW8BUAa49vxIdVguxH1AjM2CnFazWGwikrkiriyYpCdNXyWKxqa5F6SSX+xjcTauFMJAydWCCxz9CC0LC6zSz7YC2BcolygoXKpBR/UxR1t0yr2joquVFrk1DxgfeOFXkaUqs6i5IptFSZSLXCxXIuOYASsxqGTWeR3NfXbC/vXuvK/a96wOTNxoDasUIbLDvghmYPdlYToD1MBRM6ApcejMsmL5MUrsxX1z3nut7n4W0GlaxCFG1ifCsJQIEROex6DU895QgDc641Oh0q51fDAT1EIbTMuaPC2oJ9hYFqAjDsBqFt1gTjVdijxbexJUCCw4rRHmAdHfx/Ur8AGfwjdweaNEhMgtplcbXrCx/QoiYJow1bVQ/HMfdkpRknJb8YwvpYs5SEsvxpHML8Joml8q7Ui+Pbbx05VIwJ6/jgHJM8w2bihGsodg6fmyyugpKKBgcWB3Kq/8VzD4e0BAZK5qrBVqNGMxQFAduuyvZ2x4uiMzOHPEzYpsDGhXZsgn8JNGEBR4gm3U01S4tQa/0+ukM6nqrqbNBJP1AabjA+yuu4wtwhCd8gIU5EV108OZ639lxld/0aTkYCvFQIkEdxX3pkpNKhAXg0ukQSb8WRHHS55PF27m8CCM5Ar3JNiOoiVYUkPR+ynEjO9Nt+vRPqYmM/mc4Sd7D6+TtmoSMDT5wvhjV/a2Vriwaf1PU0EVFcivyyLOI1TDmdSrwwO8BzMy6dzhoMsePWI9kCCX8PAzwB3hANKA8bB7Mbw0xNjRd7K7LxlfZ+zishIAO3XvEp9P85tq4vDDX4FChl5fDcq7uAARGFu4BiIplqhWheYnBDiuGU9Y/wFmiLO8jcaDUXhXN63EwJrL6sI5H6C1fllP5/NaG6IQMOsjTcha00mt6aRsOtlsitOg/CTOAzPsdbwJOxgNMHwMGDzSbR8DCPNdf250wwljS4PIiDDY2hzXxYetWiShe7vxFC8Hmij/B6jptTehsR0qS9Bp1y0NS0MUGgPFq5+XWzrg/pKrxurrtoZTMAxUO/q2dbwimarMjB60+r2tC/k+iUbC/NjWWKxkFIP7lImYYjSq18bdbd1DDp5vFjwdDPBvoLxHGKDl/rYhznUvXAsx2LoQ0CgAoySwl27rsk1qrUe6+WRb83MLA/9TwZMcS2YMR6Itra4h2P3bxgjPg9DGLdw10Nah7mp7ktq6SIY9pWc9LceeEdJO5835i1fn71FXGc73bL71DE96mue8GlN5Fb94LdxgY9i2qJ5ZP29jibzNZfCM5Hma5p5NN+PBSXL5xe6tF79d0EZr2SnQE+mwInW1qrY93LcqgWRnZ8wZDYcOWX4NmaKH35yfv+5dhT+WLUoposezKH8H39Uesw6A1gD1tq4eQAoqLACvO7N/gj3pqk5k3tw6FANRvo36dO521kJp6rAXhQuT6PYNsn1Ciy3TEKgQ8+lHLNGrhWzrBo9CQtPcFPIFppDPReLbVIc9LIIx9S1l+Rhr5/Ky1WyMklDcIGncrORNGAd+6AXvgo4mKmVk4gJERSaDRLUBUyNQ59UmpLCpCJWiA08QL9yqZfey2p/1oO27x45dQ2EbLKNplr4kdp4uUaVAj3ImjR5aoVCL8xblV9MW1MoSg0ZTTMSr8o2y2rLMOchiooody4SHVQUK4z5nZOOBxaVcmKAsSAUj3BLuutoxlKoZw6o0tEUcPbbJKkpJjSsjeNK4salDDV+Pm6JdivtY88YIFtq0viDxuaxxTUCsgXxnxS8pux1U1MFoZxRiZC9Is2gegfAH4SwPQIiA2BeuswQVjaWBJwMHTODyd/0XFQt6NTAqhVsSOohkgLZ2QB4abAhBmaoMZpkwEVQDc9SAOarBHLXBvBb8Y6CXF4iBANH/jdekxcH7DJRaEmEdyHBPIEok7cpfU7+IV0OKqExYR58PonmD6StwplqBnHrgsQXMo9HYBPkCFJEsxCDwhYFuhY8rRHCG4FAb4LhYUVjwWG4IX1meSoNucK214DiO5crAFJN47WwyejvgoEj4FY9iRLqtk1UPXnenMrHK0rCY6nLrVVW0ajSCjRQTN3yax2vmgruMYtvdBgyMlxBcFbswEesbbXhlFaMBqomB5enk4eEz8LpFFq8xD/jq9QdGkQ/ZANokeqZrkQTFrN+LnsD4IqdaTKpktP18K3N7Py1M8eOukLWjaaSKN3EgDBIh8nb0pizMwG2XlevIJmIBmxB1MzzOsMVOiOgGN4tGmnliKjbhc1AZFNkhj1SXdeqqkdpC74Sns9hGHOvY4kwR4ygHJTvzne6GSDRMBVildvPBa6jki8NUwqUF+c7bU+N8pvq9V/1gMDzFWu+9lM8smp8EZRBTor7ZqY8OVTvWKNvUzK8rEahwbmCFcxVS4cY0FNQFdFER2IASfmWVWHt7HTjWCTIjEHQGQy7S64TpOHAtl4SWHPJbFawui3DBFiSEmR2w3qKfyPY1gdnyAE0k2SpOySAysFUQ2kiVHWQuOaEXCrQIUaxw2szFrMbTpmrcraU+VAX/OrCllZBCp08aqHdap1K1jD1Spm6S2nTZraWIaKhoWUvUHucBDga6L8Bh+d5z310a4uiqVUvnbC4ABQgZCh0zQteryrNQ6PSCf65qaY0Jteqaz1QGhyueA2yw393QoRRFACsdqKRAUOYNKq3TwO9gfaM8ID5JrwT4QUkhR4OmP9Qip5T7KNEJ1PYZEG+3NU/Sklo2viqvgboL1JLOYbT0poQa5YCUYTIRrEoDqe2S54wyQaw3ZOg7UTLIsLDLM0oR9EYDpqbWh2m12kdEB4aJJSslZJ34KST6aDj5KkFTsx3s1A9gC+JipX5YoyoCr9265zUGZ9Vs9PlD0EGJhAUVmKnnH6lggCeNudkoixuADhsSaXJyL3fqgdbJaeMOVe3mhJ6jotLLSzgZTGnddisdwwCAJfiYkunazlYLiYRHlJBI7JSlDKuFcM167wSp1Zglir+vHXSAvmhRRpe2s27X/3DUcaryZ+dxVLsCpqzgSTDCFVHtS0PTNa2NMfuQFaJBjlCUTonaELXJjVuQNhSMRm6rb67cDATxvM6bZLLcV7ntbFoUCLtlc7TNEWxSpqTQ1lnvUa/j7LOVbnLMRkEOGP7gYQGZNIGmXLFq49jFidrIq3qM0p9pNBzW9JW1dTmWbxBIaK8qbxrrrKI2Kv9mIux0qzmRyWbDSWtDcwJZ84TxyAz6C8oAU4FfpO0lOxs4TeNiiWskwV8d/NwbsQtQW/3iZV/8cKlock+tOvY6sXv9POo+r/mQK10ni5BYwpdombWlQ0esfw+w1izqCVtpbSVh7NIlreU5t61YWcxHxhwQ0DpDajckO8SKz0BL65fV0iqMixLQU5ub/WZGzQHhWSKronSpvdsU/ZHJselhWNLVtnm21ukZrySYrHds8epoEnaty8u4zfd4+Ds4Hw/9Bhp33r7kAg0RaA1hWZmlhqA1/eLk2TTOG7T5DOcInqF75D7t/gbqtAff9iUHWslm899NiLcmRDWrR8lroRLkmdJZeF5Geyqeol3EDvLQWwomEmlSheKVEfL5NFGGmrEKsHS3MuT3JAxunUHD6t4ZVrRYBgTgP7QD/4f9ndXtRLKnDzf5lLlWM/wqUw49db2EO0hWhqDtTIQ6mO1uTRjojOlY1eFMrO/3pSXqr1hAiEbV5e7KhoM5L51hGmOKTX8P5Cf6SePoMa0UlTLY3JYKDqv+YbNmA76Yh8pE2ljHxzvKOJq9Acdut3NvKiVdNB69fVM+azwp748C7R2eYKFKRTosfWW9k4HHhqeDQbeEsLV5umhpv7X1RlssTqtnKZwH7GVDGWqdZwWHLavUiirbtrL9/cED9iN6gHhYpkrNbWvdo/eeDE9Z0wSiOqMbVElNx63MdN7S9HpP8N8I/w3hH054cGdJqQ2NMffZKdNBgm5dweGIv7RkA38hH7k+SmmTn+Fp5seMPyrretS3n0fKgD7vq+SlruUZPdLPvfp4Oo5v/HEKtJdvSuEZ3APlAuTns1wf9F+bmL+hmzYZbQOqAjHDmYNE3twqybkDCcdfShLuuiY0R+c07rECf7klObz7BQy/X24n6ru/gxu+V+/LsdK0zbNYyxXMUaJ9r3P3HjPJe/RdqcSAURa/uwXODBgJVesY1+OM3YJkXTwkJfLw8o5Odp27wC12AEM3q6Rn7H89w7abw759U42bLvYb2Jbi7SNX4+436s4x6wSpAq826dX+03Az1xgDMHxah4v7UTuZakuOQowhH1Grq9BmZxVt0txlzr01Qk2eKpElOfgE9kSUU6t4rQMbNsDK59vFem/BFsmudDwJDyIXGCQxB222qiQknVUvQG+fsnJoJld4rQJdpCvLd5iMsbik7fUlpYIFI7ou/WV1TJ8KcfpV2U3fMD8Vr/js2/ygQPK4DqctdGAZ/FuCAuRkbQsHWJZxHdZWMxm2F20m+y1E3/r+K1cfBjEvDfH0AQ7zbgOP1c5dlCcuPLZx2JBtOSnh1Y4dmJM09rHXRMmP2jjULqL2DTpRXb0ibIPsUcasl1NoMNO0SCh1q0zWceMME5rSrS+r0dtV+RqNOrQdB3GbccHGAnwj4vQazHf0f1oCokpzGNsfFIpQI++2fxsx3DquldXrPvytYWpiGZSwkHbGlKmwdR0gTqugKT3slq8asYOuE9j3pgt6UVBixX7LzD1vC6BaUetdyuhVhDsqaFGVsC9ruZCtYrifbzWpeuy99r3q7tY1kWsi6EiFPikmgD72ge+qXoHKFGYcKImqY00aTUjy9BrKldnVCXZM/nnFm/el5RvM9a9Sz7SdpWkGHptON2mOltnqF2ts4m8p4MrLT1SP7Qoz2kD7xfbQfMnxLXjppLgJutu8gkEprIZAWdtAu9f0L/GQTZlKMbjVwtzOT4nj/xsI65J1jx4T3tKO4RKkziWvC2avPC56lV+GBql+rZ//IpsXuJO+oydu12rm8zAMuH7uOr0eqH7HQw+Qg+F45vTxtz6QkM3Rt9D96AN7Sj0eNISneJLGxbtYbKiPTlDEDfGBFn08uUoROIMEX8oAT9hQESO17GParacSeD2r5IVK99SQM8OeprePGc4oFm5356GZXW+WtM4MgSK6tQY3B2a2nLC00FZPrIOU+U3uaKezPAtUP39UQqmOX+yufIYR2k/p1A4SUY0T1tk+2/MYEfhNyg4iBBBCrk4N0UiGBGUR7llrtbKeKmlzV693WwFmV52ncq6B1w4+VEUv2UQGN+epfqQb+jyVBzpUxCH5MmeqRNwjxxh1DOrmNDtzfspAhLqNEX36UH6W2/6QpkoEURPVNsFZW6moV66lvXpeSTcFoaRSFfVWo/j46k0gFMFVZ3Hxjh8Wy5V0VRuP6n6T/Gxk1EILCetg6osRmLeU+suwDqucfmvoaTeHdtuw0MGMUARhlFXaAO84tWf+8iP8dymGFqQfzzDlpidRdu/r4n1/tS7Rnqxhb3RJAQWkC4Kgqw4yqyf6oB2ZoMD41xm+5wusbvBAMq7eCZuyW0Drbmwzvi0VdNtKRsBTy5I1tQm1kuIBKGoQySBAhgwCKqMPAlTbQeDo4v219AVKo1Lm3c4f+v5fWX//s1x8ARh4DuSrp0+3vP95MDh5+tXG+5+Hp8f3P/83rsb7nydcLjrgaG+8+xnUDthG+7wB+gF7LybVS6DLVETLO6A9W560ckV70agpGMs6AqBfOKE3db0NkxX4txfv3jFXWzEMjZiu30FbqyeKlK2ilcB36HbGzPnbLTQdn2GTO6czDeEO3HA6+r3XrC+b70NnZCSZdn/0ch2v43W8jtfxOl7H63gdr+N1vI7X8Tpex+t4Ha/jdbyO1/E6XsfreB2v47Xz+n+Z0e1oAHgAAA==
