## VAISAG J

+91 9061378010 | jvaisag@gmail.com | linkedin.com/in/vaisag-j | github.com/jvaisag

## PROFILE SUMMARY

Computer Science undergraduate skilled in data structures, algorithms, and full-stack, distributed, and systems-level development — from Rust/C systems programming to REST APIs, real-time streaming, and cloud-deployed microservices. Quick learner seeking to apply strong engineering fundamentals to real-world software projects.

## EDUCATION

Bachelor of Technology in Computer Science and Engineering | Sep 2023 – May 2027

## Indian Institute of Information Technology, Kottayam — Kerala, India

## TECHNICAL SKILLS

- Languages: C, C++, Rust, Python, JavaScript, SQL

- Core CS: Data Structures & Algorithms, Operating Systems, OOP, DBMS, Computer Networks

- Backend / Data: Node.js, Express.js, FastAPI, REST APIs, Microservices, PostgreSQL, Redis Streams, MongoDB, scikit-learn, Ray (distributed processing)

- Frontend: Next.js, React.js, Angular, Socket.io

- DevOps / Cloud: Docker, Docker Compose, AWS (EC2), CI/CD, Git, Linux, Nginx

- Security: IDS/Anomaly Detection, JWT, OAuth, AES Encryption, API Security, Rate Limiting

## PROJECTS

## Mini XDR — Real-Time Security Event Correlation & Anomaly Detection Platform

Node.js, Python (FastAPI, scikit-learn), Redis Streams, MongoDB, Next.js, Socket.io, Docker, AWS EC2

- Designed and built a 5-service pipeline — ingestion API, rules-based correlation engine, ML anomaly scorer, broadcast server, and live dashboard — that turns raw network sensor events into prioritized security alerts.

- Implemented a correlation engine using sliding time-windows per source IP to escalate alerts when multiple distinct attack types are seen from the same host.

- Built an online anomaly-scoring service (FastAPI + scikit-learn IsolationForest) and a real-time Next.js/Socket.io dashboard surfacing scored alerts with per-IP drill-down history.

- Deployed the full 5-service pipeline to an AWS EC2 instance, configuring security groups, port access, and process orchestration to run Redis, MongoDB, and all services in a live cloud environment.

## PgFlow — Postgres-Backed Distributed Job Scheduler

Python (asyncio), PostgreSQL (raw SQL / asyncpg), Docker Compose | github.com/jvaisag/pgflow

- Built a Celery/Airflow-style distributed job scheduler using PostgreSQL as the sole coordination layer (no external broker), supporting DAG-based job dependencies across concurrent worker processes.

- Implemented concurrency-safe job claiming using SELECT ... FOR UPDATE SKIP LOCKED, verified with automated tests spawning 10+ parallel workers to guarantee zero duplicate job processing.

- Designed dependency resolution and cycle detection using recursive CTEs to traverse and validate job DAGs before execution.

- Implemented exponential-backoff retries, a dead-letter queue for unrecoverable jobs, and leader election via Postgres advisory locks to coordinate cluster-wide sweep tasks and failed-worker recovery.

- Built a CLI for job submission, DAG inspection, dead-letter queue visibility, and live worker/leader status.

## Audio Filtering Pipeline — Data Quality Filtering for TTS Training

Python, Ray (distributed processing), SpeechBrain, Whisper, HuggingFace Datasets | github.com/jvaisag/Audio-filtering-pipeline

- Built a distributed audio data-quality pipeline for a TTS hiring assessment, processing the IndicVoices dataset (18 Indian languages) to filter low-quality samples before model training.

- Designed a multi-metric quality filter — clipping ratio, SNR, duration, and speech ratio — with each check implemented as an independent, parallelized Ray remote task, plus a SpeechBrain ECAPA-TDNN model to auto-discard language mismatches.

- Built a resumable, serializable JSONL manifest flow carrying metadata and quality metrics end-to-end, with each sample tagged KEEP/DISCARD for downstream use.

## RELEVANT COURSEWORK

Data Structures and Algorithms, Object-Oriented Programming, Operating Systems, Computer Networks, Database Management Systems, Cloud Computing, Software Engineering, Web Development

## CERTIFICATIONS & SOFT SKILLS

- Machine Learning Specialization — Coursera (DeepLearning.AI), 2024
