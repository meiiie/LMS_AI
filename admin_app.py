"""
Admin Panel for Maritime AI Tutor.

Provides interface for:
- Knowledge Base management (CRUD)
- Document upload and processing
- System monitoring

Run with: streamlit run admin_app.py --server.port 8502
"""

import os
import sys
from datetime import datetime
from typing import Optional
from uuid import uuid4

import streamlit as st

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Page config
st.set_page_config(
    page_title="Maritime AI Admin",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
.metric-card {
    background-color: #f0f2f6;
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
}
.success-msg { color: #28a745; }
.error-msg { color: #dc3545; }
.warning-msg { color: #ffc107; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "knowledge_items" not in st.session_state:
    st.session_state.knowledge_items = []

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False


def check_admin_auth():
    """Simple admin authentication."""
    if st.session_state.admin_authenticated:
        return True
    
    st.title("🔐 Admin Login")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        password = st.text_input("Admin Password", type="password")
        if st.button("Login", use_container_width=True):
            # Simple password check (in production, use proper auth)
            if password == "admin123":
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Invalid password")
    return False


def render_sidebar():
    """Render sidebar navigation."""
    with st.sidebar:
        st.title("⚙️ Admin Panel")
        st.markdown("---")
        
        page = st.radio(
            "Navigation",
            ["📊 Dashboard", "📚 Knowledge Base", "📄 Upload Documents", "👥 Users", "🔧 Settings"],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        st.caption("Maritime AI Tutor v1.0")
        
        if st.button("🚪 Logout"):
            st.session_state.admin_authenticated = False
            st.rerun()
        
        return page


def render_dashboard():
    """Render dashboard page."""
    st.title("📊 Dashboard")
    
    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Knowledge Items", len(st.session_state.knowledge_items), "+0")
    with col2:
        st.metric("Active Users", "0", "0")
    with col3:
        st.metric("Chat Sessions", "0", "0")
    with col4:
        st.metric("System Status", "🟢 Online")
    
    st.markdown("---")
    
    # System status
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🔌 Service Status")
        services = check_services()
        for service, status in services.items():
            icon = "✅" if status else "❌"
            st.write(f"{icon} {service}")
    
    with col2:
        st.subheader("📈 Recent Activity")
        st.info("No recent activity")


def check_services():
    """Check status of backend services."""
    services = {
        "API Server": False,
        "PostgreSQL": False,
        "Neo4j": False,
        "ChromaDB": False
    }
    
    try:
        import httpx
        # Check API
        try:
            r = httpx.get("http://localhost:8000/health", timeout=2)
            services["API Server"] = r.status_code == 200
        except:
            pass
        
        # Check PostgreSQL
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="localhost", port=5433,
                user="maritime", password="maritime_secret",
                dbname="maritime_ai"
            )
            conn.close()
            services["PostgreSQL"] = True
        except:
            pass
        
        # Check Neo4j
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                "bolt://localhost:7687",
                auth=("neo4j", "neo4j_secret")
            )
            driver.verify_connectivity()
            driver.close()
            services["Neo4j"] = True
        except:
            pass
        
        # Check ChromaDB
        try:
            r = httpx.get("http://localhost:8001/api/v1/heartbeat", timeout=2)
            services["ChromaDB"] = r.status_code == 200
        except:
            pass
            
    except Exception as e:
        st.error(f"Error checking services: {e}")
    
    return services


def render_knowledge_base():
    """Render knowledge base management page."""
    st.title("📚 Knowledge Base Management")
    
    # Tabs for different operations
    tab1, tab2, tab3 = st.tabs(["📋 View All", "➕ Add New", "🔍 Search"])
    
    with tab1:
        render_knowledge_list()
    
    with tab2:
        render_add_knowledge()
    
    with tab3:
        render_search_knowledge()


def render_knowledge_list():
    """Render list of knowledge items."""
    st.subheader("All Knowledge Items")
    
    if not st.session_state.knowledge_items:
        st.info("No knowledge items yet. Add some using the 'Add New' tab or upload documents.")
        
        # Quick add sample data button
        if st.button("🎯 Add Sample Maritime Data"):
            add_sample_data()
            st.rerun()
        return
    
    # Filter options
    col1, col2 = st.columns([3, 1])
    with col1:
        filter_category = st.selectbox(
            "Filter by Category",
            ["All", "COLREGs", "SOLAS", "MARPOL", "STCW", "Other"]
        )
    with col2:
        sort_by = st.selectbox("Sort by", ["Date Added", "Title", "Category"])
    
    # Display items
    items = st.session_state.knowledge_items
    if filter_category != "All":
        items = [i for i in items if i.get("category") == filter_category]
    
    for idx, item in enumerate(items):
        with st.expander(f"📄 {item['title']}", expanded=False):
            col1, col2 = st.columns([4, 1])
            
            with col1:
                st.write(f"**Category:** {item.get('category', 'N/A')}")
                st.write(f"**Added:** {item.get('created_at', 'N/A')}")
                st.text_area("Content", item.get("content", ""), height=150, disabled=True, key=f"content_{idx}", label_visibility="visible")
            
            with col2:
                if st.button("✏️ Edit", key=f"edit_{idx}"):
                    st.session_state.editing_item = idx
                if st.button("🗑️ Delete", key=f"delete_{idx}"):
                    st.session_state.knowledge_items.pop(idx)
                    st.rerun()
                if st.button("📤 Export", key=f"export_{idx}"):
                    st.download_button(
                        "Download",
                        item.get("content", ""),
                        file_name=f"{item['title']}.txt",
                        key=f"download_{idx}"
                    )


def render_add_knowledge():
    """Render form to add new knowledge item."""
    st.subheader("Add New Knowledge Item")
    
    with st.form("add_knowledge_form"):
        title = st.text_input("Title *", placeholder="e.g., COLREGs Rule 5 - Look-out")
        
        category = st.selectbox(
            "Category *",
            ["COLREGs", "SOLAS", "MARPOL", "STCW", "ISM Code", "Other"]
        )
        
        subcategory = st.text_input("Subcategory", placeholder="e.g., Part B - Steering and Sailing Rules")
        
        content = st.text_area(
            "Content *",
            height=300,
            placeholder="Enter the knowledge content here..."
        )
        
        tags = st.text_input("Tags (comma-separated)", placeholder="navigation, safety, lookout")
        
        source = st.text_input("Source", placeholder="e.g., IMO COLREG 1972")
        
        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("➕ Add Knowledge", use_container_width=True)
        with col2:
            clear = st.form_submit_button("🔄 Clear Form", use_container_width=True)
        
        if submitted:
            if not title or not content:
                st.error("Title and Content are required!")
            else:
                new_item = {
                    "id": str(uuid4()),
                    "title": title,
                    "category": category,
                    "subcategory": subcategory,
                    "content": content,
                    "tags": [t.strip() for t in tags.split(",") if t.strip()],
                    "source": source,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                st.session_state.knowledge_items.append(new_item)
                
                # Also save to Neo4j if available
                save_to_neo4j(new_item)
                
                st.success(f"✅ Added: {title}")
                st.rerun()


def render_search_knowledge():
    """Render knowledge search interface."""
    st.subheader("Search Knowledge Base")
    
    query = st.text_input("🔍 Search", placeholder="Enter search terms...")
    
    if query:
        results = []
        for item in st.session_state.knowledge_items:
            if (query.lower() in item.get("title", "").lower() or
                query.lower() in item.get("content", "").lower() or
                query.lower() in str(item.get("tags", [])).lower()):
                results.append(item)
        
        st.write(f"Found {len(results)} results")
        
        for item in results:
            with st.expander(f"📄 {item['title']}"):
                st.write(f"**Category:** {item.get('category')}")
                st.write(item.get("content", "")[:500] + "...")


def add_sample_data():
    """Add sample maritime knowledge data."""
    sample_data = [
        {
            "id": str(uuid4()),
            "title": "COLREGs Rule 5 - Look-out",
            "category": "COLREGs",
            "subcategory": "Part B - Steering and Sailing Rules",
            "content": """Every vessel shall at all times maintain a proper look-out by sight and hearing as well as by all available means appropriate in the prevailing circumstances and conditions so as to make a full appraisal of the situation and of the risk of collision.

Key points:
1. Look-out must be maintained at ALL times
2. Use both sight AND hearing
3. Use all available means (radar, AIS, etc.)
4. Purpose: Full appraisal of situation and collision risk

This rule is fundamental to safe navigation and applies to all vessels in all conditions of visibility.""",
            "tags": ["navigation", "safety", "lookout", "collision avoidance"],
            "source": "IMO COLREG 1972, as amended",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        },
        {
            "id": str(uuid4()),
            "title": "COLREGs Rule 6 - Safe Speed",
            "category": "COLREGs",
            "subcategory": "Part B - Steering and Sailing Rules",
            "content": """Every vessel shall at all times proceed at a safe speed so that she can take proper and effective action to avoid collision and be stopped within a distance appropriate to the prevailing circumstances and conditions.

Factors to consider:
1. State of visibility
2. Traffic density
3. Manoeuvrability of the vessel
4. Background light at night
5. State of wind, sea and current
6. Proximity of navigational hazards
7. Draft in relation to available depth

For vessels with radar:
- Characteristics and limitations of radar equipment
- Sea state and weather effects on radar detection
- Number, location and movement of vessels detected""",
            "tags": ["navigation", "safety", "speed", "collision avoidance"],
            "source": "IMO COLREG 1972, as amended",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        },
        {
            "id": str(uuid4()),
            "title": "SOLAS Chapter III - Life-Saving Appliances",
            "category": "SOLAS",
            "subcategory": "Chapter III",
            "content": """SOLAS Chapter III covers life-saving appliances and arrangements.

Key requirements:
1. Lifeboats - Sufficient capacity for all persons on board
2. Liferafts - Additional capacity requirements
3. Rescue boats - For rescue operations
4. Lifejackets - One for each person + extras for watch personnel
5. Lifebuoys - Minimum number based on ship length
6. Line-throwing appliances
7. Emergency signals (pyrotechnics)

Maintenance requirements:
- Weekly inspections
- Monthly inspections
- Annual servicing
- Drills and training

All life-saving appliances must be:
- Readily available
- Capable of being launched in 30 minutes
- Clearly marked and illuminated""",
            "tags": ["safety", "lifesaving", "equipment", "emergency"],
            "source": "SOLAS Convention, Chapter III",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        },
        {
            "id": str(uuid4()),
            "title": "MARPOL Annex I - Oil Pollution Prevention",
            "category": "MARPOL",
            "subcategory": "Annex I",
            "content": """MARPOL Annex I covers prevention of pollution by oil.

Key provisions:
1. Oil Record Book - Must be maintained
2. Oily water separators - 15 ppm maximum discharge
3. Special Areas - No discharge allowed (Mediterranean, Baltic, etc.)
4. Oil Discharge Monitoring Equipment (ODME)
5. Segregated Ballast Tanks (SBT)
6. Crude Oil Washing (COW)

Discharge criteria outside special areas:
- Ship is proceeding en route
- Oil content < 15 ppm
- Ship has ODME and filtering equipment
- Not within 50 nautical miles of land

Penalties for violations can include:
- Heavy fines
- Detention of vessel
- Criminal prosecution""",
            "tags": ["pollution", "oil", "environment", "discharge"],
            "source": "MARPOL 73/78, Annex I",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    ]
    
    st.session_state.knowledge_items.extend(sample_data)
    
    # Save to Neo4j
    for item in sample_data:
        save_to_neo4j(item)
    
    st.success(f"Added {len(sample_data)} sample items!")


def save_to_neo4j(item: dict) -> bool:
    """Save knowledge item to Neo4j."""
    try:
        from neo4j import GraphDatabase
        
        driver = GraphDatabase.driver(
            "bolt://localhost:7687",
            auth=("neo4j", "neo4j_secret")
        )
        
        with driver.session() as session:
            # Create knowledge node
            query = """
            MERGE (k:Knowledge {id: $id})
            SET k.title = $title,
                k.category = $category,
                k.subcategory = $subcategory,
                k.content = $content,
                k.source = $source,
                k.created_at = $created_at,
                k.updated_at = $updated_at
            
            WITH k
            MERGE (c:Category {name: $category})
            MERGE (k)-[:BELONGS_TO]->(c)
            
            RETURN k.id as id
            """
            
            result = session.run(query, **item)
            record = result.single()
            
            # Create tag nodes and relationships
            if item.get("tags"):
                for tag in item["tags"]:
                    tag_query = """
                    MATCH (k:Knowledge {id: $id})
                    MERGE (t:Tag {name: $tag})
                    MERGE (k)-[:HAS_TAG]->(t)
                    """
                    session.run(tag_query, id=item["id"], tag=tag)
        
        driver.close()
        return True
        
    except Exception as e:
        st.warning(f"Could not save to Neo4j: {e}")
        return False


def render_upload_documents():
    """Render document upload page."""
    st.title("📄 Upload Documents")
    
    st.info("""
    Upload maritime documents to automatically extract and add to the knowledge base.
    
    **Supported formats:** TXT, PDF (coming soon), DOCX (coming soon)
    """)
    
    uploaded_file = st.file_uploader(
        "Choose a file",
        type=["txt", "md"],
        help="Upload text files containing maritime knowledge"
    )
    
    if uploaded_file:
        st.write(f"**File:** {uploaded_file.name}")
        st.write(f"**Size:** {uploaded_file.size} bytes")
        
        # Read content
        content = uploaded_file.read().decode("utf-8")
        
        st.subheader("Preview")
        st.text_area("Content Preview", content[:2000], height=200, disabled=True)
        
        # Processing options
        st.subheader("Processing Options")
        
        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox(
                "Category",
                ["COLREGs", "SOLAS", "MARPOL", "STCW", "ISM Code", "Other"]
            )
        with col2:
            chunk_size = st.slider("Chunk Size (chars)", 500, 5000, 2000)
        
        auto_tags = st.checkbox("Auto-generate tags", value=True)
        
        if st.button("📥 Process and Import", use_container_width=True):
            with st.spinner("Processing document..."):
                # Simple chunking
                chunks = chunk_text(content, chunk_size)
                
                for i, chunk in enumerate(chunks):
                    item = {
                        "id": str(uuid4()),
                        "title": f"{uploaded_file.name} - Part {i+1}",
                        "category": category,
                        "subcategory": "",
                        "content": chunk,
                        "tags": extract_tags(chunk) if auto_tags else [],
                        "source": uploaded_file.name,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                    }
                    st.session_state.knowledge_items.append(item)
                    save_to_neo4j(item)
                
                st.success(f"✅ Imported {len(chunks)} chunks from {uploaded_file.name}")


def chunk_text(text: str, chunk_size: int = 2000) -> list:
    """Split text into chunks."""
    chunks = []
    
    # Split by paragraphs first
    paragraphs = text.split("\n\n")
    
    current_chunk = ""
    for para in paragraphs:
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks


def extract_tags(text: str) -> list:
    """Extract relevant tags from text."""
    # Simple keyword extraction
    maritime_keywords = [
        "navigation", "safety", "collision", "vessel", "ship",
        "radar", "lookout", "speed", "lights", "signals",
        "lifesaving", "fire", "pollution", "oil", "cargo",
        "anchor", "mooring", "pilot", "port", "starboard",
        "SOLAS", "COLREGs", "MARPOL", "STCW", "ISM"
    ]
    
    text_lower = text.lower()
    found_tags = []
    
    for keyword in maritime_keywords:
        if keyword.lower() in text_lower:
            found_tags.append(keyword)
    
    return found_tags[:5]  # Limit to 5 tags


def render_users():
    """Render users management page."""
    st.title("👥 User Management")
    
    st.info("User management features coming soon...")
    
    # Placeholder stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Users", "0")
    with col2:
        st.metric("Active Today", "0")
    with col3:
        st.metric("New This Week", "0")


def render_settings():
    """Render settings page."""
    st.title("🔧 Settings")
    
    tab1, tab2, tab3 = st.tabs(["🔌 Connections", "🤖 AI Settings", "🔐 Security"])
    
    with tab1:
        st.subheader("Database Connections")
        
        with st.expander("PostgreSQL", expanded=True):
            st.text_input("Host", value="localhost")
            st.text_input("Port", value="5433")
            st.text_input("Database", value="maritime_ai")
            if st.button("Test PostgreSQL Connection"):
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host="localhost", port=5433,
                        user="maritime", password="maritime_secret",
                        dbname="maritime_ai"
                    )
                    conn.close()
                    st.success("✅ Connected!")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
        
        with st.expander("Neo4j"):
            st.text_input("URI", value="bolt://localhost:7687")
            if st.button("Test Neo4j Connection"):
                try:
                    from neo4j import GraphDatabase
                    driver = GraphDatabase.driver(
                        "bolt://localhost:7687",
                        auth=("neo4j", "neo4j_secret")
                    )
                    driver.verify_connectivity()
                    driver.close()
                    st.success("✅ Connected!")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
        
        with st.expander("ChromaDB"):
            st.text_input("Host", value="localhost", key="chroma_host")
            st.text_input("Port", value="8001", key="chroma_port")
            if st.button("Test ChromaDB Connection"):
                try:
                    import httpx
                    r = httpx.get("http://localhost:8001/api/v1/heartbeat", timeout=2)
                    if r.status_code == 200:
                        st.success("✅ Connected!")
                    else:
                        st.error(f"❌ Status: {r.status_code}")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
    
    with tab2:
        st.subheader("AI Model Settings")
        
        model = st.selectbox(
            "LLM Model",
            ["x-ai/grok-4.1-fast:free", "gpt-4o-mini", "gpt-4o", "claude-3-sonnet"]
        )
        
        temperature = st.slider("Temperature", 0.0, 1.0, 0.7)
        max_tokens = st.slider("Max Tokens", 100, 4000, 1000)
        
        st.text_input("OpenRouter API Key", type="password", value="sk-or-v1-***")
    
    with tab3:
        st.subheader("Security Settings")
        
        st.text_input("Admin Password", type="password")
        st.text_input("API Key", type="password", value="test-api-key-123")
        
        st.checkbox("Enable Rate Limiting", value=True)
        st.number_input("Requests per minute", value=100)


# Main app
def main():
    if not check_admin_auth():
        return
    
    page = render_sidebar()
    
    if page == "📊 Dashboard":
        render_dashboard()
    elif page == "📚 Knowledge Base":
        render_knowledge_base()
    elif page == "📄 Upload Documents":
        render_upload_documents()
    elif page == "👥 Users":
        render_users()
    elif page == "🔧 Settings":
        render_settings()


if __name__ == "__main__":
    main()
