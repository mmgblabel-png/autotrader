FROM node:22-alpine

WORKDIR /app

COPY package.json tsconfig.json hardhat.config.ts ./
RUN npm install --no-audit --no-fund

COPY contracts ./contracts
COPY scripts ./scripts
COPY test ./test
COPY config ./config

RUN npm run check

CMD ["node", "-e", "require('http').createServer((req,res)=>{res.statusCode=200;res.end('ok')}).listen(process.env.PORT||3000)"]
