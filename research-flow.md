xóa research demo cũ, tạo research demo mới với ý tưởng đơn giản hơn và có sẵn phân rã ý tưởng theo các thành phần:
Problem
Research question
Gap candidate
Contribution
Claim
Evidence
Constraint
Open question

Sau mỗi lần người dùng nhấn Confirm thành công, hiển thị thông báo "Saved. Select
Continue to proceed to the next step." Confirm không tự chuyển bước. Chỉ giữ nút
Continue để bắt đầu hoặc chuyển sang bước tiếp theo, không dùng nút Start.
Nếu người dùng nhấn Continue khi Working Draft hiện tại chưa được Confirm, giữ
nguyên bước hiện tại và hiển thị thông báo tiếng Anh: "This work has not been
confirmed. Select Confirm to save it before continuing."

Phần dưới đây là luồng related work tôi muốn sửa. Ngoài ra thống nhất ngôn ngữ hiển thị ở related work là tiếng anh (hiện tại có 1 vài chỗ đang để tiếng việt)

Đến phần related work, ở research input, hệ thống sẽ dùng LLM tự động dựa vào ý tưởng đã được phân rã ở bước phía trước để tạo sẵn vài keyword có liên qua tới ý tưởng đó. Người dùng vẫn có thể tự thêm keyword nếu muốn. Sau khi đã hoàn tất phần research input thì nhấn confirm để lưu lại (hiện tại trong code là generate suggestions, nên đổi lại thành confirm và thay đổi chức năng thành lưu lại research input).

Research Inputs không tự generate hoặc regenerate keyword khi truy cập. Người dùng
chủ động nhấn Generate/Regenerate keyword suggestions; keyword đã save phải được
giữ nguyên khi truy cập lại cho tới khi người dùng tự chỉnh sửa hoặc nhấn Regenerate.
Keyword phải giữ lại các concept phân biệt trực tiếp của idea (target artifact/task,
intervention hoặc mechanism, outcome và constraint), không được thay thế chúng bằng
các thuật ngữ học thuật chung chung. Concept lấy trực tiếp từ idea được ưu tiên và
được bổ sung lại nếu model bỏ sót.

Tiếp đến related work, chỉ giữ lại search và analyze, xóa phần điền query, hệ thống dùng LLM dựa vào research input để tìm và phân tích, sau đó đưa ra bảng đối sánh related work. Thêm nữa, với mỗi nhận định đưa ra phải chỉ ra được nội dung nào được sử dụng để đưa ra nhận định đó nằm ở phần nào, mục nào trong nguồn. Sau khi hoàn tất nhấn confirm để lưu related work.
Mọi concept phân biệt phải được bao phủ trong tập search query. Hệ thống tìm ứng viên
từ toàn bộ query rồi xếp hạng theo mức bao phủ concept trong title/abstract, ưu tiên
đủ các concept khác nhau và loại tài liệu chỉ liên quan chung chung. Search mới thay
thế working results của lần search trước để tài liệu cũ không tiếp tục tích lũy.

Cuối cùng đến gap, chỉ tạo 1 gap candidate, với nội dung là tổng hợp của các related work sau khi trả lời các câu hỏi:
Gap không được tự generate khi người dùng truy cập. Khi chưa có hoặc muốn tạo lại,
người dùng chủ động nhấn Generate/Regenerate Gap Candidate; nội dung đã save phải
được giữ nguyên khi truy cập lại.
Nghiên cứu trước đã làm được gì?
Điểm nào vẫn còn hạn chế?
Vì sao hạn chế đó quan trọng?
Có thể kiểm nghiệm bằng thí nghiệm nào?

Bốn câu trả lời này chỉ được xử lý nội bộ để phục vụ bước tổng hợp, không hiển thị
thành các trường riêng trên frontend. Việc phân tích phải sử dụng toàn bộ Related
Work đã tìm được, không chỉ chọn một vài nguồn đại diện.

-> Từ đó rút ra gap candidate chung: 
Ví dụ gap candidate
Các phương pháp tối ưu prompt hiện tại có thể sử dụng điểm tổng hoặc textual feedback. Chưa rõ việc tách output thành từng claim, kiểm tra evidence độc lập và dùng lỗi claim-level làm feedback có giúp giảm unsupported claims trong cùng ngân sách inference hay không.

Frontend chỉ hiển thị một nội dung Gap Candidate đã được tổng hợp và tóm gọn.
Người dùng chỉ được phép sửa nội dung tóm gọn này.

Sau khi confirm lưu gap candidate, phần Related Work hiển thị nút Generate Contribution Direction để người dùng chủ động quyết định khi nào tạo các hướng. Hệ thống không tự generate khi truy cập hoặc truy cập lại. Các hướng đã generate và lựa chọn đã save phải được giữ nguyên. Danh sách có 2 hướng cố định ko đổi là Kết hợp và Other. Contribution Direction không nằm ở một phần Contribution riêng. Kết hợp sẽ cho chọn một contribution chính và các contribution phụ. Other cho người dùng tự nhập hướng riêng. 

Sau khi Confirm Contribution Direction, chỉ hiển thị thông báo "Saved." và không
hiển thị nút Continue.

Dưới đây là ví dụ với idea là "Tôi muốn xây dựng phương pháp tự động tối ưu prompt nhiều vòng để giảm hallucination khi LLM trích xuất thông tin từ paper." thì hệ thống sẽ đưa ra các hướng như sau:
A. Tập trung vào thuật toán tối ưu prompt
Điểm mới nằm ở mutation, selection hoặc search.
B. Tập trung vào claim–evidence verifier
Điểm mới nằm ở cách kiểm tra hallucination.
C. Tập trung vào human-in-the-loop
Điểm mới nằm ở cách người dùng xác nhận và điều chỉnh quá trình.
D. Kết hợp các hướng
Chọn một contribution chính và các contribution phụ.
E. Other
Người dùng nhập hướng riêng.

Sau khi người dùng chọn xong thì lưu lại

