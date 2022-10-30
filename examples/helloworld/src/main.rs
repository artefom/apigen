mod server;

struct State {}

impl server::ServerState for State {}

#[tokio::main]
async fn main() -> Result<(), std::io::Error> {
    server::run_server("127.0.0.1:8000", State {}).await?;

    Ok(())
}
