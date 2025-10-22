# Security Policy

**Table of Contents**
- [English](#vulnerability-management)
- [한국어 (Korean)](#보안-정책-한국어)


> **⚠️ Security Notice** 
> This application is designed for personal use on a private network. Due to potential security risks, **do not expose this application to the public internet.**

---

## Vulnerability Management

Thank you for helping keep SolaSola secure. We appreciate your efforts and responsible disclosure.

### Supported Versions

We are committed to providing security updates for the latest version of SolaSola. Please ensure you are using the most recent release available on Docker Hub.

| Version | Supported          |
| ------- | ------------------ |
| `0.1.x`   | :white_check_mark: |
| `< 0.1.x` | :x:                |

### Third-Party Dependencies

SolaSola relies on numerous open-source libraries. We actively monitor these dependencies for security vulnerabilities using tools like Trivy as part of our automated CI/CD pipeline. When a patch for a `CRITICAL` or `HIGH` severity vulnerability in a dependency becomes available, we are committed to applying it and releasing a new version in a timely manner.

### User-Initiated Scans

Users can independently check the vulnerability status of the SolaSola Docker image through the Docker Desktop GUI or by using command-line tools like `docker scout`.

```bash
docker scout cves castika/solasola:latest
```

If you discover a vulnerability that has an available patch but has not yet been addressed in the latest version of SolaSola, we encourage you to report it privately following the "How to Report" instructions below.

We take all security vulnerabilities seriously. If you believe you have found a security vulnerability in SolaSola, please report it to us privately.

**Please do NOT report security vulnerabilities through public GitHub issues.**

### How to Report

1.  Go to the **"Security"** tab of the SolaSola GitHub repository.
2.  Click on **"Report a vulnerability"**.
3.  Fill out the form with as much detail as possible.

### What to Include

To help us resolve the issue quickly, please include the following information in your report:

-   A clear and concise description of the vulnerability.
-   The version of SolaSola affected.
-   Steps to reproduce the vulnerability, including any specific configurations or input files.
-   The potential impact of the vulnerability (e.g., data exposure, denial of service).
-   Any suggested mitigations or fixes, if you have any.

### Our Process

1.  **Acknowledgement**: We will acknowledge receipt of your report within **3 business days**.
2.  **Initial Assessment**: We will provide an initial assessment of the vulnerability's severity and potential impact within **7 business days**.
3.  **Updates**: We will strive to keep you updated on our progress as we work to validate and fix the vulnerability.
4.  **Disclosure**: Once the vulnerability is resolved, we will create a new release and publish a security advisory, giving you credit for the discovery if you wish.

---

## 보안 정책 (한국어)

> **⚠️ 보안 공지**
> 이 애플리케이션은 개인 네트워크에서의 개인적인 사용을 위해 설계되었습니다. 잠재적인 보안 위험으로 인해, **이 애플리케이션을 공용 인터넷에 노출하지 마세요.**

---

## 취약점 관리

SolaSola를 안전하게 유지하는 데 도움을 주셔서 감사합니다. 여러분의 노력과 책임감 있는 정보 공개에 감사드립니다.

### 지원 버전

저희는 SolaSola의 최신 버전에 대한 보안 업데이트를 제공하기 위해 최선을 다하고 있습니다. Docker Hub에서 제공되는 가장 최신 릴리스를 사용하고 있는지 확인해 주세요.

| 버전    | 지원 여부          |
| ------- | ------------------ |
| `0.1.x`   | :white_check_mark: |
| `< 0.1.x` | :x:                |

### 서드파티 의존성

SolaSola는 수많은 오픈 소스 라이브러리에 의존합니다. 저희는 자동화된 CI/CD 파이프라인의 일부로 Trivy와 같은 도구를 사용하여 이러한 의존성의 보안 취약점을 적극적으로 모니터링합니다. 의존성에서 `CRITICAL` 또는 `HIGH` 심각도의 취약점에 대한 패치가 제공되면, 저희는 시기적절하게 패치를 적용하고 새로운 버전을 릴리스하기 위해 최선을 다할 것을 약속합니다.

### 사용자 주도 스캔

사용자는 Docker Desktop GUI를 통하거나 `docker scout`와 같은 커맨드 라인 도구를 사용하여 SolaSola Docker 이미지의 취약점 상태를 독립적으로 확인할 수 있습니다.

```bash
docker scout cves castika/solasola:latest
```

만약 사용 가능한 패치가 있지만 아직 SolaSola의 최신 버전에 반영되지 않은 취약점을 발견한 경우, 아래의 '보고 방법' 지침에 따라 비공개로 보고해 주시기를 권장합니다.

저희는 모든 보안 취약점을 심각하게 받아들입니다. SolaSola에서 보안 취약점을 발견했다고 생각되면, 저희에게 비공개로 보고해 주세요.

**공개적인 GitHub 이슈를 통해 보안 취약점을 보고하지 마세요.**

### 보고 방법

1.  SolaSola GitHub 리포지토리의 **"Security"** 탭으로 이동합니다.
2.  **"Report a vulnerability"**를 클릭합니다.
3.  가능한 한 상세하게 양식을 작성합니다.

### 포함할 내용

문제를 신속하게 해결할 수 있도록, 보고서에 다음 정보를 포함해 주세요:

-   취약점에 대한 명확하고 간결한 설명.
-   영향을 받는 SolaSola의 버전.
-   특정 설정이나 입력 파일을 포함한, 취약점을 재현하는 단계.
-   취약점의 잠재적 영향 (예: 데이터 노출, 서비스 거부).
-   제안할 수 있는 완화 조치나 수정 사항 (있을 경우).

### 처리 절차

1.  **확인**: 보고서를 받은 후 **영업일 기준 3일** 이내에 접수를 확인합니다.
2.  **초기 평가**: **영업일 기준 7일** 이내에 취약점의 심각성 및 잠재적 영향에 대한 초기 평가를 제공합니다.
3.  **업데이트**: 취약점을 검증하고 수정하는 동안 진행 상황에 대해 계속 업데이트해 드리기 위해 노력할 것입니다.
4.  **공개**: 취약점이 해결되면, 새로운 릴리스를 생성하고 보안 권고를 게시하며, 원하실 경우 발견에 대한 크레딧을 드립니다.
